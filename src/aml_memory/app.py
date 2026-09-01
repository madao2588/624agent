"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from aml_memory.config import Settings
from aml_memory.errors import RequestConflictError
from aml_memory.retrieval import LexicalRetrievalPipeline
from aml_memory.schemas import AddRequest, AddResponse, SearchRequest, SearchResponse
from aml_memory.service import MemoryService
from aml_memory.store import MemoryStore

logger = logging.getLogger("aml_memory")


def create_app(
    *,
    database_path: str | Path | None = None,
    neighbor_radius: int | None = None,
) -> FastAPI:
    """Build an application with injectable filesystem configuration."""

    settings = Settings.from_environment()
    settings = Settings(
        database_path=Path(database_path) if database_path is not None else settings.database_path,
        neighbor_radius=(
            neighbor_radius if neighbor_radius is not None else settings.neighbor_radius
        ),
    )
    store = MemoryStore(settings.database_path)
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=settings.neighbor_radius)
    service = MemoryService(store, retrieval)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        app.state.settings = settings
        app.state.store = store
        app.state.memory_service = service
        yield

    app = FastAPI(title="AML Memory Candidate", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        store.check()
        return {"status": "ok"}

    @app.post("/add", response_model=AddResponse, include_in_schema=False)
    @app.post("/v1/memories/add", response_model=AddResponse)
    def add_memory(request: AddRequest) -> AddResponse:
        try:
            response = service.add(request)
        except RequestConflictError as error:
            logger.warning("add_conflict request_id=%s", request.request_id)
            raise HTTPException(
                status_code=409,
                detail="request_id already exists with a different payload",
            ) from error
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
    )
    @app.post(
        "/v1/memories/search",
        response_model=SearchResponse,
        response_model_exclude_none=True,
    )
    def search_memory(request: SearchRequest) -> SearchResponse:
        response = service.search(request)
        logger.info(
            "search_complete user_id=%s returned=%d",
            request.user_id,
            len(response.data),
        )
        return response

    return app


app = create_app()
