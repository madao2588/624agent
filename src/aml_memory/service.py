"""Application service coordinating durable writes and evidence retrieval."""

from __future__ import annotations

from aml_memory.formatting import format_evidence
from aml_memory.ports import MemoryWriter, RetrievalPipeline
from aml_memory.schemas import AddRequest, AddResponse, SearchRequest, SearchResponse


class MemoryService:
    def __init__(self, store: MemoryWriter, retrieval: RetrievalPipeline) -> None:
        self._store = store
        self._retrieval = retrieval

    def add(self, request: AddRequest) -> AddResponse:
        self._store.add(request)
        return AddResponse(
            success=True,
            request_id=request.request_id,
            user_id=request.user_id,
            session_id=request.session_id,
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        search_text = " ".join([request.query, *(request.options or [])])
        results = self._retrieval.search(
            query=search_text,
            user_id=request.user_id,
            top_k=request.top_k,
        )
        return SearchResponse(
            data=[format_evidence(result.message, score=result.score) for result in results]
        )
