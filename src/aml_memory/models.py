"""Internal immutable models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Literal

FacetKind = Literal[
    "entity",
    "alias",
    "coreference",
    "place",
    "date",
    "time_expression",
    "event",
    "event_status",
    "preference",
    "aversion",
    "habit",
    "one_off",
    "rule_condition",
    "rule_requirement",
    "rule_prohibition",
    "rule_order",
    "rule_exception",
    "safety",
]


@dataclass(frozen=True, slots=True)
class MemoryFacet:
    kind: FacetKind
    value: str
    normalized_value: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.value.strip() or not self.normalized_value.strip():
            raise ValueError("memory facet values must not be blank")
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError("memory facet confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class MessageAnalysis:
    facets: tuple[MemoryFacet, ...]


@dataclass(frozen=True, slots=True)
class StoredMessage:
    id: str
    sequence: int
    request_id: str
    user_id: str
    session_id: str
    ordinal: int
    role: str
    occurred_at_ms: int | None
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AddResult:
    inserted: bool
    message_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """Validated vectors produced together by one embedding model."""

    model: str
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("embedding model must not be blank")
        if not self.vectors:
            raise ValueError("embedding batch must not be empty")

        normalized = tuple(tuple(float(value) for value in vector) for vector in self.vectors)
        dimensions = len(normalized[0])
        if dimensions == 0:
            raise ValueError("embedding vectors must not be empty")
        for vector in normalized:
            if len(vector) != dimensions:
                raise ValueError("embedding vectors must have equal dimensions")
            if not all(isfinite(value) for value in vector):
                raise ValueError("embedding vectors must contain only finite values")
            if not any(value != 0.0 for value in vector):
                raise ValueError("embedding vectors must not be zero vectors")
        object.__setattr__(self, "vectors", normalized)

    @property
    def dimensions(self) -> int:
        return len(self.vectors[0])


@dataclass(frozen=True, slots=True)
class ScoredMessage:
    message: StoredMessage
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RelatedMessage:
    message: StoredMessage
    hop: int
    anchor: str


@dataclass(frozen=True, slots=True)
class MemoryRelation:
    source_id: str
    target_id: str
    relation: str
    anchor: str
    confidence: float
