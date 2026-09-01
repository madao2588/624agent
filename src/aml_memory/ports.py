"""Structural interfaces that keep API, storage, and retrieval replaceable."""

from __future__ import annotations

from typing import Protocol

from aml_memory.models import AddResult, ScoredMessage, StoredMessage
from aml_memory.schemas import AddRequest


class MemoryWriter(Protocol):
    def add(self, request: AddRequest) -> AddResult: ...


class RetrievalStore(Protocol):
    def search_fts(
        self, *, user_id: str, fts_query: str, limit: int
    ) -> list[tuple[StoredMessage, float]]: ...

    def list_session_messages(
        self, *, user_id: str, session_id: str
    ) -> list[StoredMessage]: ...


class RetrievalPipeline(Protocol):
    def search(self, *, query: str, user_id: str, top_k: int) -> list[ScoredMessage]: ...
