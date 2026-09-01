"""Internal immutable models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
class ScoredMessage:
    message: StoredMessage
    score: float
