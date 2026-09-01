"""Deterministic lexical retrieval and context expansion."""

from __future__ import annotations

import re

from aml_memory.models import ScoredMessage, StoredMessage
from aml_memory.ports import RetrievalStore

_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)


def build_fts_query(query: str) -> str | None:
    """Convert untrusted natural language into a safe FTS disjunction."""

    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_PATTERN.finditer(query):
        token = match.group(0).casefold()
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    if not tokens:
        return None
    return " OR ".join(f'"{token}"' for token in tokens)


class LexicalRetrievalPipeline:
    """FTS5 baseline with same-session neighbor expansion."""

    def __init__(self, store: RetrievalStore, *, neighbor_radius: int = 1) -> None:
        if neighbor_radius < 0:
            raise ValueError("neighbor_radius must not be negative")
        self._store = store
        self._neighbor_radius = neighbor_radius

    def search(self, *, query: str, user_id: str, top_k: int) -> list[ScoredMessage]:
        if top_k <= 0:
            return []
        fts_query = build_fts_query(query)
        if fts_query is None:
            return []

        hits = self._store.search_fts(user_id=user_id, fts_query=fts_query, limit=top_k)
        selected: dict[str, ScoredMessage] = {}

        for rank, (message, _lexical_score) in enumerate(hits):
            selected[message.id] = ScoredMessage(message=message, score=1.0 / (rank + 1))

        if self._neighbor_radius:
            session_cache: dict[str, list[StoredMessage]] = {}
            for rank, (hit, _lexical_score) in enumerate(hits):
                session_messages = session_cache.setdefault(
                    hit.session_id,
                    self._store.list_session_messages(
                        user_id=user_id, session_id=hit.session_id
                    ),
                )
                hit_index = next(
                    index for index, message in enumerate(session_messages) if message.id == hit.id
                )
                for distance in range(1, self._neighbor_radius + 1):
                    for neighbor_index in (hit_index - distance, hit_index + distance):
                        if not 0 <= neighbor_index < len(session_messages):
                            continue
                        neighbor = session_messages[neighbor_index]
                        selected.setdefault(
                            neighbor.id,
                            ScoredMessage(
                                message=neighbor,
                                score=(1.0 / (rank + 1)) / (distance + 1),
                            ),
                        )

        ranked = sorted(
            selected.values(),
            key=lambda result: (-result.score, result.message.sequence),
        )
        return ranked[:top_k]
