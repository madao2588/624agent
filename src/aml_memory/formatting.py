"""Leaderboard evidence formatting."""

from __future__ import annotations

from datetime import UTC, datetime

from aml_memory.models import StoredMessage
from aml_memory.schemas import MemoryEvidence


def _source_timestamp(occurred_at_ms: int) -> str:
    value = datetime.fromtimestamp(occurred_at_ms / 1000, tz=UTC)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def format_evidence(message: StoredMessage, *, score: float) -> MemoryEvidence:
    """Render an immutable source message without paraphrasing it."""

    prefix = message.role.upper()
    if message.occurred_at_ms is not None:
        prefix = f"[{_source_timestamp(message.occurred_at_ms)}] {prefix}"
    return MemoryEvidence(
        id=message.id,
        content=f"{prefix}: {message.content}",
        score=score,
        created_at=message.created_at,
    )
