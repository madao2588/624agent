"""Process-local retrieval-provider connections with sliding expiry."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import monotonic
from typing import Literal

from aml_memory.models import EmbeddingBatch
from aml_memory.ports import Embedder, QueryExpander

EmbeddingProvider = Literal["local", "openai", "openai-compatible"]
RetrievalProvider = Literal["local", "openai", "openai-compatible", "deepseek"]
RetrievalCapability = Literal["embedding", "query-expansion"]


class EmbeddingConnectionNotFoundError(LookupError):
    """Raised when a retrieval connection is unknown or expired."""


class EmbeddingSpaceEmbedder:
    """Give one provider/model vector space a stable storage identifier."""

    def __init__(
        self,
        delegate: Embedder,
        *,
        provider: EmbeddingProvider,
        public_model: str,
        base_url: str,
    ) -> None:
        space = "\0".join((provider, base_url, public_model)).encode()
        digest = hashlib.sha256(space).hexdigest()[:16]
        self.model = f"{public_model}::{digest}"
        self._delegate = delegate

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        batch = self._delegate.embed(texts)
        return EmbeddingBatch(model=self.model, vectors=batch.vectors)


@dataclass(frozen=True, slots=True)
class EmbeddingConnection:
    connection_id: str
    provider: RetrievalProvider
    capability: RetrievalCapability
    model: str
    base_url: str
    embedder: Embedder | None
    query_expander: QueryExpander | None
    expires_at: datetime


@dataclass(slots=True)
class _ConnectionRecord:
    connection_id: str
    provider: RetrievalProvider
    capability: RetrievalCapability
    model: str
    base_url: str
    embedder: Embedder | None
    query_expander: QueryExpander | None
    expires_at_monotonic: float


class EmbeddingConnectionRegistry:
    """Keep provider clients reachable only through opaque, expiring IDs."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 1_800,
        clock: Callable[[], float] = monotonic,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("connection TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._records: dict[str, _ConnectionRecord] = {}
        self._lock = RLock()

    def add(
        self,
        *,
        provider: RetrievalProvider,
        model: str,
        base_url: str,
        embedder: Embedder | None = None,
        query_expander: QueryExpander | None = None,
    ) -> EmbeddingConnection:
        if (embedder is None) == (query_expander is None):
            raise ValueError("connection requires exactly one retrieval capability")
        capability: RetrievalCapability = (
            "embedding" if embedder is not None else "query-expansion"
        )
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            connection_id = self._new_id()
            record = _ConnectionRecord(
                connection_id=connection_id,
                provider=provider,
                capability=capability,
                model=model,
                base_url=base_url,
                embedder=embedder,
                query_expander=query_expander,
                expires_at_monotonic=now + self._ttl_seconds,
            )
            self._records[connection_id] = record
            return self._snapshot(record, now=now)

    def resolve(self, connection_id: str) -> EmbeddingConnection:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            record = self._records.get(connection_id)
            if record is None:
                raise EmbeddingConnectionNotFoundError(connection_id)
            record.expires_at_monotonic = now + self._ttl_seconds
            return self._snapshot(record, now=now)

    def describe(self, connection_id: str) -> EmbeddingConnection:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            record = self._records.get(connection_id)
            if record is None:
                raise EmbeddingConnectionNotFoundError(connection_id)
            return self._snapshot(record, now=now)

    def delete(self, connection_id: str) -> bool:
        with self._lock:
            return self._records.pop(connection_id, None) is not None

    def _new_id(self) -> str:
        connection_id = secrets.token_urlsafe(24)
        while connection_id in self._records:
            connection_id = secrets.token_urlsafe(24)
        return connection_id

    def _purge_expired(self, now: float) -> None:
        expired = [
            connection_id
            for connection_id, record in self._records.items()
            if record.expires_at_monotonic <= now
        ]
        for connection_id in expired:
            del self._records[connection_id]

    def _snapshot(
        self, record: _ConnectionRecord, *, now: float
    ) -> EmbeddingConnection:
        remaining_seconds = max(0.0, record.expires_at_monotonic - now)
        return EmbeddingConnection(
            connection_id=record.connection_id,
            provider=record.provider,
            capability=record.capability,
            model=record.model,
            base_url=record.base_url,
            embedder=record.embedder,
            query_expander=record.query_expander,
            expires_at=self._utc_now() + timedelta(seconds=remaining_seconds),
        )
