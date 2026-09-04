"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse

from aml_memory.auth import ApiKeyAuthenticator
from aml_memory.config import Settings
from aml_memory.connections import (
    EmbeddingConnection,
    EmbeddingConnectionNotFoundError,
    EmbeddingConnectionRegistry,
    EmbeddingSpaceEmbedder,
)
from aml_memory.embeddings import FastEmbedEmbedder, OpenAICompatibleEmbedder
from aml_memory.enrichment import OpenAIEvaluationProvider
from aml_memory.errors import RequestConflictError, RetrievalProviderError
from aml_memory.formatting import format_evidence
from aml_memory.ports import (
    Embedder,
    EvaluationProvider,
    QueryExpander,
    RetrievalPipeline,
)
from aml_memory.query_expansion import DeepSeekQueryExpander
from aml_memory.retrieval import (
    HybridRetrievalPipeline,
    LexicalRetrievalPipeline,
    QueryExpansionRetrievalPipeline,
)
from aml_memory.schemas import (
    AddRequest,
    AddResponse,
    DiagnosticFacet,
    DiagnosticMemoryEvidence,
    DiagnosticRelation,
    EmbeddingConnectionCreate,
    EmbeddingConnectionDeleteResponse,
    EmbeddingConnectionResponse,
    RetrievalConnectionCreate,
    RetrievalConnectionDeleteResponse,
    RetrievalConnectionResponse,
    SearchDiagnosticsResponse,
    SearchRequest,
    SearchResponse,
)
from aml_memory.service import MemoryService
from aml_memory.store import MemoryStore

logger = logging.getLogger("aml_memory")
DEMO_PAGE = Path(__file__).with_name("demo.html")
CONNECTION_TEST_TEXT = "AML Memory connection test"
CONNECTION_TEST_QUERY = "Find memories about a changed meeting plan."
_DEFAULT_LOCAL_EMBEDDER = FastEmbedEmbedder()


def _default_connection_embedder_factory(
    config: EmbeddingConnectionCreate,
) -> Embedder:
    if config.provider == "local":
        return _DEFAULT_LOCAL_EMBEDDER
    assert config.api_key is not None
    return OpenAICompatibleEmbedder(
        api_key=config.api_key.get_secret_value(),
        model=config.resolved_model,
        base_url=config.resolved_base_url,
    )


def _default_connection_query_expander_factory(
    config: RetrievalConnectionCreate,
) -> QueryExpander:
    assert config.api_key is not None
    return DeepSeekQueryExpander(
        api_key=config.api_key.get_secret_value(),
        model=config.resolved_model,
        base_url=config.resolved_base_url,
    )


def _connection_response(
    connection: EmbeddingConnection,
) -> EmbeddingConnectionResponse:
    return EmbeddingConnectionResponse(
        connection_id=connection.connection_id,
        provider=connection.provider,
        model=connection.model,
        base_url=connection.base_url,
        expires_at=connection.expires_at,
    )


def _retrieval_connection_response(
    connection: EmbeddingConnection,
) -> RetrievalConnectionResponse:
    return RetrievalConnectionResponse(
        connection_id=connection.connection_id,
        provider=connection.provider,
        capability=connection.capability,
        model=connection.model,
        base_url=connection.base_url,
        expires_at=connection.expires_at,
    )


def create_app(
    *,
    database_path: str | Path | None = None,
    neighbor_radius: int | None = None,
    auth_scheme: str | None = None,
    api_key: str | None = None,
    embedder: Embedder | None = None,
    evaluation_provider: EvaluationProvider | None = None,
    connection_embedder_factory: Callable[[EmbeddingConnectionCreate], Embedder]
    | None = None,
    connection_query_expander_factory: Callable[
        [RetrievalConnectionCreate], QueryExpander
    ]
    | None = None,
    connection_registry: EmbeddingConnectionRegistry | None = None,
) -> FastAPI:
    """Build an application with injectable filesystem configuration."""

    settings = Settings.from_environment()
    settings = Settings(
        database_path=Path(database_path) if database_path is not None else settings.database_path,
        runtime_mode=settings.runtime_mode,
        neighbor_radius=(
            neighbor_radius if neighbor_radius is not None else settings.neighbor_radius
        ),
        auth_scheme=auth_scheme if auth_scheme is not None else settings.auth_scheme,
        api_key=api_key if api_key is not None else settings.api_key,
        embedding_provider=settings.embedding_provider,
        embedding_api_key=settings.embedding_api_key,
        embedding_model=settings.embedding_model,
        embedding_base_url=settings.embedding_base_url,
        embedding_dimensions=settings.embedding_dimensions,
        embedding_timeout_seconds=settings.embedding_timeout_seconds,
        evaluation_api_key=settings.evaluation_api_key,
        evaluation_model=settings.evaluation_model,
        evaluation_profile=settings.evaluation_profile,
    )
    store = MemoryStore(settings.database_path)
    active_embedder = embedder
    if active_embedder is None and settings.embedding_provider == "openai-compatible":
        if settings.embedding_api_key is None:
            raise ValueError("embedding API key is required")
        active_embedder = OpenAICompatibleEmbedder(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            dimensions=settings.embedding_dimensions,
            timeout_seconds=settings.embedding_timeout_seconds,
        )
    retrieval: RetrievalPipeline
    active_evaluation_provider = evaluation_provider
    if settings.runtime_mode == "evaluation":
        if active_embedder is not None:
            raise ValueError("evaluation mode does not allow an embedding override")
        profile = settings.evaluation_profile
        if profile is None or settings.evaluation_api_key is None:
            raise ValueError("evaluation mode requires its frozen provider settings")
        if active_evaluation_provider is None:
            active_evaluation_provider = OpenAIEvaluationProvider(
                api_key=settings.evaluation_api_key,
                model=profile.model,
                timeout_seconds=profile.provider_timeout_seconds,
                max_attempts=profile.provider_max_attempts,
                circuit_failure_threshold=profile.circuit_failure_threshold,
                circuit_cooldown_seconds=profile.circuit_cooldown_seconds,
            )
        retrieval = QueryExpansionRetrievalPipeline(
            store,
            active_evaluation_provider,
            neighbor_radius=settings.neighbor_radius,
            lexical_candidate_limit=profile.lexical_candidate_limit,
            facet_candidate_limit=profile.facet_candidate_limit,
            graph_hops=profile.graph_hops,
            relevance_threshold=profile.relevance_threshold,
        )
    elif active_embedder is None:
        retrieval = LexicalRetrievalPipeline(
            store,
            neighbor_radius=settings.neighbor_radius,
        )
    else:
        retrieval = HybridRetrievalPipeline(
            store,
            active_embedder,
            neighbor_radius=settings.neighbor_radius,
        )
    service = MemoryService(
        store,
        retrieval,
        embedder=active_embedder,
        enricher=active_evaluation_provider,
    )
    registry = connection_registry or EmbeddingConnectionRegistry()
    build_connection_embedder = (
        connection_embedder_factory or _default_connection_embedder_factory
    )
    build_connection_query_expander = (
        connection_query_expander_factory
        or _default_connection_query_expander_factory
    )
    authenticate = ApiKeyAuthenticator(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        app.state.settings = settings
        app.state.store = store
        app.state.memory_service = service
        app.state.embedding_connections = registry
        app.state.retrieval_connections = registry
        yield

    app = FastAPI(title="AML Memory Candidate", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        try:
            store.check()
        except Exception as error:
            logger.error("health_storage_not_ready")
            raise HTTPException(
                status_code=503,
                detail="memory store not ready",
            ) from error
        return {"status": "ok"}

    @app.get("/demo", include_in_schema=False)
    def demo() -> FileResponse:
        return FileResponse(
            DEMO_PAGE,
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    def build_connection(request: RetrievalConnectionCreate) -> EmbeddingConnection:
        try:
            if request.provider == "deepseek":
                query_expander = build_connection_query_expander(request)
                query_expander.expand(CONNECTION_TEST_QUERY)
                connection = registry.add(
                    provider=request.provider,
                    model=request.resolved_model,
                    base_url=request.resolved_base_url,
                    query_expander=query_expander,
                )
            else:
                candidate = build_connection_embedder(request)
                candidate.embed([CONNECTION_TEST_TEXT])
                connection_embedder = EmbeddingSpaceEmbedder(
                    candidate,
                    provider=request.provider,
                    public_model=request.resolved_model,
                    base_url=request.resolved_base_url,
                )
                connection = registry.add(
                    provider=request.provider,
                    model=request.resolved_model,
                    base_url=request.resolved_base_url,
                    embedder=connection_embedder,
                )
        except RetrievalProviderError as error:
            logger.warning(
                "retrieval_connection_probe_failed provider=%s model=%s",
                request.provider,
                request.resolved_model,
            )
            raise HTTPException(status_code=503, detail=str(error)) from error
        logger.info(
            "retrieval_connection_created provider=%s model=%s capability=%s",
            connection.provider,
            connection.model,
            connection.capability,
        )
        return connection

    @app.post(
        "/v1/retrieval-connections",
        response_model=RetrievalConnectionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authenticate)],
    )
    def create_retrieval_connection(
        request: RetrievalConnectionCreate,
    ) -> RetrievalConnectionResponse:
        return _retrieval_connection_response(build_connection(request))

    @app.post(
        "/v1/embedding-connections",
        response_model=EmbeddingConnectionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(authenticate)],
    )
    def create_embedding_connection(
        request: EmbeddingConnectionCreate,
    ) -> EmbeddingConnectionResponse:
        return _connection_response(build_connection(request))

    def describe_connection(connection_id: str) -> EmbeddingConnection:
        try:
            return registry.describe(connection_id)
        except EmbeddingConnectionNotFoundError as error:
            raise HTTPException(
                status_code=401,
                detail="embedding connection is invalid or expired",
            ) from error

    @app.get(
        "/v1/retrieval-connections/{connection_id}",
        response_model=RetrievalConnectionResponse,
        dependencies=[Depends(authenticate)],
    )
    def get_retrieval_connection(connection_id: str) -> RetrievalConnectionResponse:
        return _retrieval_connection_response(describe_connection(connection_id))

    @app.get(
        "/v1/embedding-connections/{connection_id}",
        response_model=EmbeddingConnectionResponse,
        dependencies=[Depends(authenticate)],
    )
    def get_embedding_connection(connection_id: str) -> EmbeddingConnectionResponse:
        return _connection_response(describe_connection(connection_id))

    @app.delete(
        "/v1/retrieval-connections/{connection_id}",
        response_model=RetrievalConnectionDeleteResponse,
        dependencies=[Depends(authenticate)],
    )
    def delete_retrieval_connection(
        connection_id: str,
    ) -> RetrievalConnectionDeleteResponse:
        registry.delete(connection_id)
        return RetrievalConnectionDeleteResponse()

    @app.delete(
        "/v1/embedding-connections/{connection_id}",
        response_model=EmbeddingConnectionDeleteResponse,
        dependencies=[Depends(authenticate)],
    )
    def delete_embedding_connection(
        connection_id: str,
    ) -> EmbeddingConnectionDeleteResponse:
        registry.delete(connection_id)
        return EmbeddingConnectionDeleteResponse()

    def service_for_connection(connection_id: str | None) -> MemoryService:
        if connection_id is None:
            return service
        if settings.runtime_mode == "evaluation":
            raise HTTPException(
                status_code=400,
                detail="temporary retrieval connections are disabled in evaluation mode",
            )
        try:
            connection = registry.resolve(connection_id)
        except EmbeddingConnectionNotFoundError as error:
            raise HTTPException(
                status_code=401,
                detail="embedding connection is invalid or expired",
            ) from error
        if connection.embedder is not None:
            dynamic_retrieval: RetrievalPipeline = HybridRetrievalPipeline(
                store,
                connection.embedder,
                neighbor_radius=settings.neighbor_radius,
            )
            return MemoryService(store, dynamic_retrieval, embedder=connection.embedder)
        assert connection.query_expander is not None
        dynamic_retrieval = QueryExpansionRetrievalPipeline(
            store,
            connection.query_expander,
            neighbor_radius=settings.neighbor_radius,
        )
        return MemoryService(store, dynamic_retrieval)

    def selected_connection_id(
        retrieval_connection: str | None,
        embedding_connection: str | None,
    ) -> str | None:
        if (
            retrieval_connection is not None
            and embedding_connection is not None
            and retrieval_connection != embedding_connection
        ):
            raise HTTPException(status_code=400, detail="connection headers disagree")
        return retrieval_connection or embedding_connection

    @app.post(
        "/add",
        response_model=AddResponse,
        include_in_schema=False,
        dependencies=[Depends(authenticate)],
    )
    @app.post(
        "/v1/memories/add",
        response_model=AddResponse,
        dependencies=[Depends(authenticate)],
    )
    def add_memory(
        request: AddRequest,
        retrieval_connection: str | None = Header(
            default=None, alias="X-Retrieval-Connection"
        ),
        embedding_connection: str | None = Header(
            default=None, alias="X-Embedding-Connection"
        ),
    ) -> AddResponse:
        request_service = service_for_connection(
            selected_connection_id(retrieval_connection, embedding_connection)
        )
        try:
            response = request_service.add(request)
        except RequestConflictError as error:
            logger.warning("add_conflict request_id=%s", request.request_id)
            raise HTTPException(
                status_code=409,
                detail="request_id already exists with a different payload",
            ) from error
        except RetrievalProviderError as error:
            logger.error("add_retrieval_provider_failed request_id=%s", request.request_id)
            raise HTTPException(status_code=503, detail=str(error)) from error
        logger.info(
            "add_complete request_id=%s user_id=%s messages=%d",
            request.request_id,
            request.user_id,
            len(request.messages),
        )
        return response

    @app.post(
        "/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        include_in_schema=False,
        dependencies=[Depends(authenticate)],
    )
    @app.post(
        "/v1/memories/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(authenticate)],
    )
    def search_memory(
        request: SearchRequest,
        retrieval_connection: str | None = Header(
            default=None, alias="X-Retrieval-Connection"
        ),
        embedding_connection: str | None = Header(
            default=None, alias="X-Embedding-Connection"
        ),
    ) -> SearchResponse:
        request_service = service_for_connection(
            selected_connection_id(retrieval_connection, embedding_connection)
        )
        try:
            response = request_service.search(request)
        except RetrievalProviderError as error:
            logger.error("search_retrieval_provider_failed user_id=%s", request.user_id)
            raise HTTPException(status_code=503, detail=str(error)) from error
        logger.info(
            "search_complete user_id=%s returned=%d",
            request.user_id,
            len(response.data),
        )
        return response

    @app.post(
        "/v1/memories/search/diagnostics",
        response_model=SearchDiagnosticsResponse,
        response_model_exclude_none=True,
        include_in_schema=False,
        dependencies=[Depends(authenticate)],
    )
    def search_memory_diagnostics(
        request: SearchRequest,
        retrieval_connection: str | None = Header(
            default=None, alias="X-Retrieval-Connection"
        ),
        embedding_connection: str | None = Header(
            default=None, alias="X-Embedding-Connection"
        ),
    ) -> SearchDiagnosticsResponse:
        request_service = service_for_connection(
            selected_connection_id(retrieval_connection, embedding_connection)
        )
        try:
            results = request_service.search_scored(request)
        except RetrievalProviderError as error:
            logger.error(
                "search_diagnostics_provider_failed user_id=%s", request.user_id
            )
            raise HTTPException(status_code=503, detail=str(error)) from error

        message_ids = [result.message.id for result in results]
        facets_by_id = store.list_message_facets(
            user_id=request.user_id,
            message_ids=message_ids,
        )
        relations = store.list_diagnostic_relations(
            user_id=request.user_id,
            message_ids=message_ids,
        )
        forgotten_ids = store.list_forgotten_message_ids(
            user_id=request.user_id,
            message_ids=message_ids,
        )
        history_ids = {
            relation.target_id
            for relation in relations
            if relation.relation == "supersedes"
        }

        evidence: list[DiagnosticMemoryEvidence] = []
        for result in results:
            message_id = result.message.id
            facets = facets_by_id.get(message_id, ())
            event_statuses = {
                facet.normalized_value
                for facet in facets
                if facet.kind == "event_status"
            }
            memory_state: Literal["active", "history", "cancelled", "forgotten"]
            if message_id in forgotten_ids or "forget" in event_statuses:
                memory_state = "forgotten"
            elif message_id in history_ids:
                memory_state = "history"
            elif "cancel" in event_statuses:
                memory_state = "cancelled"
            else:
                memory_state = "active"
            formatted = format_evidence(result.message, score=result.score)
            evidence.append(
                DiagnosticMemoryEvidence(
                    **formatted.model_dump(),
                    reasons=list(result.reasons or ("ranked",)),
                    facets=[
                        DiagnosticFacet(
                            kind=facet.kind,
                            value=facet.value,
                            normalized_value=facet.normalized_value,
                            confidence=facet.confidence,
                        )
                        for facet in facets
                    ],
                    state=memory_state,
                )
            )
        return SearchDiagnosticsResponse(
            data=evidence,
            relations=[
                DiagnosticRelation(
                    source_id=relation.source_id,
                    target_id=relation.target_id,
                    relation=relation.relation,
                    anchor=relation.anchor,
                    confidence=relation.confidence,
                )
                for relation in relations
            ],
        )

    return app


app = create_app()
