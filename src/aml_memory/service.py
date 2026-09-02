"""Application service coordinating durable writes and evidence retrieval."""

from __future__ import annotations

from aml_memory.formatting import format_evidence
from aml_memory.models import ScoredMessage
from aml_memory.ports import Embedder, MemoryEnricher, MemoryWriter, RetrievalPipeline
from aml_memory.schemas import AddRequest, AddResponse, SearchRequest, SearchResponse


class MemoryService:
    def __init__(
        self,
        store: MemoryWriter,
        retrieval: RetrievalPipeline,
        *,
        embedder: Embedder | None = None,
        enricher: MemoryEnricher | None = None,
    ) -> None:
        self._store = store
        self._retrieval = retrieval
        self._embedder = embedder
        self._enricher = enricher

    def add(self, request: AddRequest) -> AddResponse:
        existing = self._store.find_existing(request)
        if existing is None:
            enrichment_facets = None
            if self._enricher is not None:
                enrichment_facets = self._enricher.enrich(
                    [message.content for message in request.messages]
                )
            embeddings = None
            if self._embedder is not None:
                embeddings = self._embedder.embed(
                    [message.content for message in request.messages]
                )
            self._store.add(
                request,
                embeddings=embeddings,
                enrichment_facets=enrichment_facets,
            )
        return AddResponse(
            success=True,
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        results = self.search_scored(request)
        return SearchResponse(
            data=[format_evidence(result.message, score=result.score) for result in results]
        )

    def search_scored(self, request: SearchRequest) -> list[ScoredMessage]:
        search_text = " ".join([request.query, *(request.options or [])])
        return self._retrieval.search(
            query=search_text,
            user_id=request.user_id,
            top_k=request.top_k,
            strong_terms=tuple(request.options or ()),
        )
