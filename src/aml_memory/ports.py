"""Structural interfaces that keep API, storage, and retrieval replaceable."""

from __future__ import annotations

from typing import Protocol

from aml_memory.models import (
    AddResult,
    EmbeddingBatch,
    MemoryFacet,
    RelatedMessage,
    ScoredMessage,
    StoredMessage,
)
from aml_memory.schemas import AddRequest
from aml_memory.tags import MemoryTag


class MemoryWriter(Protocol):
    def find_existing(self, request: AddRequest) -> AddResult | None: ...

    def add(
        self,
        request: AddRequest,
        *,
        embeddings: EmbeddingBatch | None = None,
        enrichment_facets: tuple[tuple[MemoryFacet, ...], ...] | None = None,
    ) -> AddResult: ...


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


class QueryExpander(Protocol):
    def expand(self, query: str) -> list[str]: ...


class MemoryEnricher(Protocol):
    def enrich(self, contents: list[str]) -> tuple[tuple[MemoryFacet, ...], ...]: ...


class EvaluationProvider(MemoryEnricher, QueryExpander, Protocol):
    """The fixed evaluation dependency used by both Add and Search."""


class RetrievalStore(Protocol):
    def search_fts(
        self, *, user_id: str, fts_query: str, limit: int
    ) -> list[tuple[StoredMessage, float]]: ...

    def list_session_messages(
        self, *, user_id: str, session_id: str
    ) -> list[StoredMessage]: ...

    def list_state_chain(
        self,
        *,
        user_id: str,
        message_ids: list[str],
        limit: int,
    ) -> list[StoredMessage]: ...

    def list_tagged_messages(
        self,
        *,
        user_id: str,
        kind: MemoryTag,
        limit: int,
    ) -> list[StoredMessage]: ...

    def list_message_facets(
        self,
        *,
        user_id: str,
        message_ids: list[str],
    ) -> dict[str, tuple[MemoryFacet, ...]]: ...

    def search_facets(
        self,
        *,
        user_id: str,
        facets: tuple[MemoryFacet, ...],
        limit: int,
    ) -> list[StoredMessage]: ...

    def list_forgotten_message_ids(
        self,
        *,
        user_id: str,
        message_ids: list[str],
    ) -> set[str]: ...

    def list_related_messages(
        self,
        *,
        user_id: str,
        message_ids: list[str],
        max_hops: int,
        limit: int,
    ) -> list[RelatedMessage]: ...

    def search_vectors(
        self,
        *,
        user_id: str,
        model: str,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> list[tuple[StoredMessage, float]]: ...


class RetrievalPipeline(Protocol):
    def search(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int,
        strong_terms: tuple[str, ...] = (),
    ) -> list[ScoredMessage]: ...
