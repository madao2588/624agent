"""SQLite persistence with transactional Add semantics."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from aml_memory.analysis import analyze_batch
from aml_memory.errors import RequestConflictError
from aml_memory.lexical import lexical_index_text
from aml_memory.models import (
    AddResult,
    EmbeddingBatch,
    FacetKind,
    MemoryFacet,
    MemoryRelation,
    MessageAnalysis,
    RelatedMessage,
    StoredMessage,
)
from aml_memory.schemas import AddRequest
from aml_memory.state import build_state_candidate_query, select_superseded_message
from aml_memory.tags import MemoryTag, classify_message

_SCHEMA = """
CREATE TABLE IF NOT EXISTS add_requests (
    request_id TEXT PRIMARY KEY,
    payload_hash TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    occurred_at_ms INTEGER,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES add_requests(request_id) ON DELETE CASCADE,
    UNIQUE (request_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_messages_user_sequence
    ON messages(user_id, sequence);
CREATE INDEX IF NOT EXISTS idx_messages_user_session_sequence
    ON messages(user_id, session_id, sequence);

CREATE TABLE IF NOT EXISTS state_relations (
    newer_message_id TEXT NOT NULL,
    older_message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation = 'supersedes'),
    created_at TEXT NOT NULL,
    PRIMARY KEY (newer_message_id, older_message_id, relation),
    CHECK (newer_message_id <> older_message_id),
    FOREIGN KEY (newer_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (older_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_state_relations_user_newer
    ON state_relations(user_id, newer_message_id);
CREATE INDEX IF NOT EXISTS idx_state_relations_user_older
    ON state_relations(user_id, older_message_id);

CREATE TABLE IF NOT EXISTS message_tags (
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('preference', 'procedure')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, kind),
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_tags_user_kind
    ON message_tags(user_id, kind, message_id);

CREATE TABLE IF NOT EXISTS message_facets (
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence > 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, kind, normalized_value),
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_facets_user_kind_value
    ON message_facets(user_id, kind, normalized_value, message_id);
CREATE INDEX IF NOT EXISTS idx_message_facets_user_message
    ON message_facets(user_id, message_id);

CREATE TABLE IF NOT EXISTS memory_relations (
    source_message_id TEXT NOT NULL,
    target_message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    anchor TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence > 0.0 AND confidence <= 1.0),
    created_at TEXT NOT NULL,
    PRIMARY KEY (source_message_id, target_message_id, relation, anchor),
    CHECK (source_message_id <> target_message_id),
    FOREIGN KEY (source_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (target_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_relations_user_source
    ON memory_relations(user_id, source_message_id);
CREATE INDEX IF NOT EXISTS idx_memory_relations_user_target
    ON memory_relations(user_id, target_message_id);

CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED,
    user_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS message_vectors (
    message_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_vectors_user_model_dimensions
    ON message_vectors(user_id, model, dimensions);
"""

_REQUIRED_SCHEMA_OBJECTS = frozenset(
    {
        "messages",
        "messages_fts",
        "message_facets",
        "memory_relations",
        "state_relations",
        "schema_metadata",
        "idx_message_facets_user_kind_value",
        "idx_memory_relations_user_source",
        "idx_state_relations_user_newer",
    }
)


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _payload_hash(request: AddRequest) -> str:
    serialized = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _message_id(request_id: str, ordinal: int) -> str:
    digest = hashlib.sha256(f"{request_id}\0{ordinal}".encode()).hexdigest()
    return f"mem_{digest[:32]}"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stored_message(row: sqlite3.Row) -> StoredMessage:
    return StoredMessage(
        id=str(row["id"]),
        sequence=int(row["sequence"]),
        request_id=str(row["request_id"]),
        user_id=str(row["user_id"]),
        session_id=str(row["session_id"]),
        ordinal=int(row["ordinal"]),
        role=str(row["role"]),
        occurred_at_ms=(
            int(row["occurred_at_ms"]) if row["occurred_at_ms"] is not None else None
        ),
        content=str(row["content"]),
        created_at=_parse_datetime(str(row["created_at"])),
    )


def _pack_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack_vector(value: bytes, dimensions: int) -> tuple[float, ...]:
    expected_bytes = dimensions * 4
    if len(value) != expected_bytes:
        raise ValueError("stored embedding has an invalid byte length")
    return tuple(struct.unpack(f"<{dimensions}f", value))


def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("vectors must have matching non-zero dimensions")
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("vectors must not be zero vectors")
    return dot_product / (left_norm * right_norm)


def _merge_facets(
    local: tuple[MemoryFacet, ...],
    enriched: tuple[MemoryFacet, ...],
) -> tuple[MemoryFacet, ...]:
    merged: dict[tuple[str, str], MemoryFacet] = {
        (facet.kind, facet.normalized_value): facet for facet in local
    }
    for facet in enriched:
        key = (facet.kind, facet.normalized_value)
        existing = merged.get(key)
        if existing is None or facet.confidence > existing.confidence:
            merged[key] = facet
    return tuple(merged.values())


class MemoryStore:
    """Concrete durable store; each operation owns its SQLite connection."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(_SCHEMA)
            self._backfill_lexical_index(connection)
            self._backfill_message_tags(connection)
            self._backfill_message_facets(connection)
            self._backfill_memory_relations(connection)
            connection.commit()

    def check(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE name IN (
                    'messages',
                    'messages_fts',
                    'message_facets',
                    'memory_relations',
                    'state_relations',
                    'schema_metadata',
                    'idx_message_facets_user_kind_value',
                    'idx_memory_relations_user_source',
                    'idx_state_relations_user_newer'
                )
                """
            ).fetchall()
        present = {str(row["name"]) for row in rows}
        if present != _REQUIRED_SCHEMA_OBJECTS:
            raise RuntimeError("memory store schema is incomplete")

    def find_existing(self, request: AddRequest) -> AddResult | None:
        """Resolve idempotency before optional external enrichment work."""

        digest = _payload_hash(request)
        message_ids = tuple(
            _message_id(request.request_id, ordinal)
            for ordinal, _message in enumerate(request.messages)
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_hash FROM add_requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
        if existing is None:
            return None
        if str(existing["payload_hash"]) != digest:
            raise RequestConflictError(
                f"request_id {request.request_id!r} already has a different payload"
            )
        return AddResult(inserted=False, message_ids=message_ids)

    def add(
        self,
        request: AddRequest,
        *,
        embeddings: EmbeddingBatch | None = None,
        enrichment_facets: tuple[tuple[MemoryFacet, ...], ...] | None = None,
    ) -> AddResult:
        if embeddings is not None and len(embeddings.vectors) != len(request.messages):
            raise ValueError("embedding batch must contain one vector per message")
        if enrichment_facets is not None and len(enrichment_facets) != len(
            request.messages
        ):
            raise ValueError("enrichment must contain one facet group per message")
        analyses = analyze_batch(
            [(message.content, message.timestamp) for message in request.messages]
        )
        if enrichment_facets is not None:
            analyses = tuple(
                MessageAnalysis(
                    facets=_merge_facets(analysis.facets, enrichment_facets[index])
                )
                for index, analysis in enumerate(analyses)
            )

        digest = _payload_hash(request)
        message_ids = tuple(
            _message_id(request.request_id, ordinal)
            for ordinal, _message in enumerate(request.messages)
        )

        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT payload_hash FROM add_requests WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_hash"]) != digest:
                        raise RequestConflictError(
                            f"request_id {request.request_id!r} already has a different payload"
                        )
                    if embeddings is not None:
                        self._write_vectors(
                            connection,
                            message_ids=message_ids,
                            user_id=request.user_id,
                            embeddings=embeddings,
                            created_at=_utc_now_text(),
                        )
                    connection.commit()
                    return AddResult(inserted=False, message_ids=message_ids)

                created_at = _utc_now_text()
                connection.execute(
                    """
                    INSERT INTO add_requests(
                        request_id, payload_hash, user_id, session_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        digest,
                        request.user_id,
                        request.session_id,
                        created_at,
                    ),
                )
                for ordinal, message in enumerate(request.messages):
                    memory_id = message_ids[ordinal]
                    connection.execute(
                        """
                        INSERT INTO messages(
                            id, request_id, user_id, session_id, ordinal, role,
                            occurred_at_ms, content, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            memory_id,
                            request.request_id,
                            request.user_id,
                            request.session_id,
                            ordinal,
                            message.role,
                            message.timestamp,
                            message.content,
                            created_at,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO messages_fts(message_id, user_id, content) VALUES (?, ?, ?)",
                        (
                            memory_id,
                            request.user_id,
                            lexical_index_text(message.content),
                        ),
                    )
                    self._write_message_tags(
                        connection,
                        message_id=memory_id,
                        user_id=request.user_id,
                        content=message.content,
                        created_at=created_at,
                    )
                    self._write_message_facets(
                        connection,
                        message_id=memory_id,
                        user_id=request.user_id,
                        facets=analyses[ordinal].facets,
                        created_at=created_at,
                    )
                    self._link_explicit_state_update(
                        connection,
                        newer_message_id=memory_id,
                        user_id=request.user_id,
                        content=message.content,
                        occurred_at_ms=message.timestamp,
                        created_at=created_at,
                    )
                    self._link_structured_state_update(
                        connection,
                        newer_message_id=memory_id,
                        user_id=request.user_id,
                        facets=analyses[ordinal].facets,
                        created_at=created_at,
                    )
                    self._link_shared_facets(
                        connection,
                        newer_message_id=memory_id,
                        user_id=request.user_id,
                        facets=analyses[ordinal].facets,
                        created_at=created_at,
                    )
                if embeddings is not None:
                    self._write_vectors(
                        connection,
                        message_ids=message_ids,
                        user_id=request.user_id,
                        embeddings=embeddings,
                        created_at=created_at,
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return AddResult(inserted=True, message_ids=message_ids)

    def add_benchmark_lexical(
        self,
        request: AddRequest,
        *,
        embeddings: EmbeddingBatch | None = None,
    ) -> AddResult:
        """Persist raw benchmark sources without building facets or relations.

        This path exists for large retrieval-only benchmark replays. Production
        API writes must continue to use :meth:`add` so memory governance,
        structured recall, and relation expansion stay enabled.
        """

        if embeddings is not None and len(embeddings.vectors) != len(request.messages):
            raise ValueError("embedding batch must contain one vector per message")
        digest = _payload_hash(request)
        message_ids = tuple(
            _message_id(request.request_id, ordinal)
            for ordinal, _message in enumerate(request.messages)
        )
        with self._connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT payload_hash FROM add_requests WHERE request_id = ?",
                    (request.request_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_hash"]) != digest:
                        raise RequestConflictError(
                            f"request_id {request.request_id!r} already has a different payload"
                        )
                    if embeddings is not None:
                        self._write_vectors(
                            connection,
                            message_ids=message_ids,
                            user_id=request.user_id,
                            embeddings=embeddings,
                            created_at=_utc_now_text(),
                        )
                    connection.commit()
                    return AddResult(inserted=False, message_ids=message_ids)

                created_at = _utc_now_text()
                connection.execute(
                    """
                    INSERT INTO add_requests(
                        request_id, payload_hash, user_id, session_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id,
                        digest,
                        request.user_id,
                        request.session_id,
                        created_at,
                    ),
                )
                for ordinal, message in enumerate(request.messages):
                    memory_id = message_ids[ordinal]
                    connection.execute(
                        """
                        INSERT INTO messages(
                            id, request_id, user_id, session_id, ordinal, role,
                            occurred_at_ms, content, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            memory_id,
                            request.request_id,
                            request.user_id,
                            request.session_id,
                            ordinal,
                            message.role,
                            message.timestamp,
                            message.content,
                            created_at,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO messages_fts(message_id, user_id, content) "
                        "VALUES (?, ?, ?)",
                        (
                            memory_id,
                            request.user_id,
                            lexical_index_text(message.content),
                        ),
                    )
                if embeddings is not None:
                    self._write_vectors(
                        connection,
                        message_ids=message_ids,
                        user_id=request.user_id,
                        embeddings=embeddings,
                        created_at=created_at,
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return AddResult(inserted=True, message_ids=message_ids)

    @staticmethod
    def _backfill_lexical_index(connection: sqlite3.Connection) -> None:
        migration_key = "messages_fts_lexical_terms_v2"
        existing = connection.execute(
            "SELECT 1 FROM schema_metadata WHERE key = ?",
            (migration_key,),
        ).fetchone()
        if existing is not None:
            return
        rows = connection.execute(
            "SELECT id, user_id, content FROM messages ORDER BY sequence"
        ).fetchall()
        connection.execute("DELETE FROM messages_fts")
        for row in rows:
            connection.execute(
                "INSERT INTO messages_fts(message_id, user_id, content) VALUES (?, ?, ?)",
                (
                    str(row["id"]),
                    str(row["user_id"]),
                    lexical_index_text(str(row["content"])),
                ),
            )
        connection.execute(
            """
            INSERT INTO schema_metadata(key, value, updated_at)
            VALUES (?, 'complete', ?)
            """,
            (migration_key, _utc_now_text()),
        )

    @staticmethod
    def _write_message_tags(
        connection: sqlite3.Connection,
        *,
        message_id: str,
        user_id: str,
        content: str,
        created_at: str,
    ) -> None:
        for kind in classify_message(content):
            connection.execute(
                """
                INSERT OR IGNORE INTO message_tags(message_id, user_id, kind, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, user_id, kind, created_at),
            )

    @classmethod
    def _backfill_message_tags(cls, connection: sqlite3.Connection) -> None:
        migration_key = "message_tags_backfill_v1"
        existing = connection.execute(
            "SELECT 1 FROM schema_metadata WHERE key = ?",
            (migration_key,),
        ).fetchone()
        if existing is not None:
            return
        rows = connection.execute(
            "SELECT id, user_id, content, created_at FROM messages ORDER BY sequence"
        ).fetchall()
        for row in rows:
            cls._write_message_tags(
                connection,
                message_id=str(row["id"]),
                user_id=str(row["user_id"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
            )
        now = _utc_now_text()
        connection.execute(
            """
            INSERT INTO schema_metadata(key, value, updated_at)
            VALUES (?, 'complete', ?)
            """,
            (migration_key, now),
        )

    @staticmethod
    def _write_message_facets(
        connection: sqlite3.Connection,
        *,
        message_id: str,
        user_id: str,
        facets: tuple[MemoryFacet, ...],
        created_at: str,
    ) -> None:
        for facet in facets:
            connection.execute(
                """
                INSERT OR IGNORE INTO message_facets(
                    message_id, user_id, kind, value, normalized_value,
                    confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    user_id,
                    facet.kind,
                    facet.value,
                    facet.normalized_value,
                    facet.confidence,
                    created_at,
                ),
            )

    @classmethod
    def _backfill_message_facets(cls, connection: sqlite3.Connection) -> None:
        migration_key = "message_facets_backfill_v1"
        existing = connection.execute(
            "SELECT 1 FROM schema_metadata WHERE key = ?",
            (migration_key,),
        ).fetchone()
        if existing is not None:
            return
        rows = connection.execute(
            """
            SELECT id, user_id, session_id, occurred_at_ms, content, created_at
            FROM messages
            ORDER BY user_id, session_id, sequence
            """
        ).fetchall()
        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            key = (str(row["user_id"]), str(row["session_id"]))
            grouped.setdefault(key, []).append(row)
        for group_rows in grouped.values():
            analyses = analyze_batch(
                [
                    (
                        str(row["content"]),
                        (
                            int(row["occurred_at_ms"])
                            if row["occurred_at_ms"] is not None
                            else None
                        ),
                    )
                    for row in group_rows
                ]
            )
            for row, analysis in zip(group_rows, analyses, strict=True):
                cls._write_message_facets(
                    connection,
                    message_id=str(row["id"]),
                    user_id=str(row["user_id"]),
                    facets=analysis.facets,
                    created_at=str(row["created_at"]),
                )
        connection.execute(
            """
            INSERT INTO schema_metadata(key, value, updated_at)
            VALUES (?, 'complete', ?)
            """,
            (migration_key, _utc_now_text()),
        )

    @classmethod
    def _backfill_memory_relations(cls, connection: sqlite3.Connection) -> None:
        migration_key = "memory_relations_backfill_v1"
        existing = connection.execute(
            "SELECT 1 FROM schema_metadata WHERE key = ?",
            (migration_key,),
        ).fetchone()
        if existing is not None:
            return
        rows = connection.execute(
            """
            SELECT id, user_id, created_at
            FROM messages
            ORDER BY sequence
            """
        ).fetchall()
        for row in rows:
            facet_rows = connection.execute(
                """
                SELECT kind, value, normalized_value, confidence
                FROM message_facets
                WHERE user_id = ? AND message_id = ?
                ORDER BY kind, normalized_value
                """,
                (str(row["user_id"]), str(row["id"])),
            ).fetchall()
            facets = tuple(
                MemoryFacet(
                    kind=cast(FacetKind, str(facet_row["kind"])),
                    value=str(facet_row["value"]),
                    normalized_value=str(facet_row["normalized_value"]),
                    confidence=float(facet_row["confidence"]),
                )
                for facet_row in facet_rows
            )
            cls._link_structured_state_update(
                connection,
                newer_message_id=str(row["id"]),
                user_id=str(row["user_id"]),
                facets=facets,
                created_at=str(row["created_at"]),
            )
            cls._link_shared_facets(
                connection,
                newer_message_id=str(row["id"]),
                user_id=str(row["user_id"]),
                facets=facets,
                created_at=str(row["created_at"]),
            )
        connection.execute(
            """
            INSERT INTO schema_metadata(key, value, updated_at)
            VALUES (?, 'complete', ?)
            """,
            (migration_key, _utc_now_text()),
        )

    @staticmethod
    def _link_explicit_state_update(
        connection: sqlite3.Connection,
        *,
        newer_message_id: str,
        user_id: str,
        content: str,
        occurred_at_ms: int | None,
        created_at: str,
    ) -> None:
        candidate_query = build_state_candidate_query(content)
        if candidate_query is None:
            return
        rows = connection.execute(
            """
            SELECT m.sequence, m.id, m.request_id, m.user_id, m.session_id,
                   m.ordinal, m.role, m.occurred_at_ms, m.content, m.created_at,
                   bm25(messages_fts) AS lexical_score
            FROM messages_fts
            JOIN messages AS m ON m.id = messages_fts.message_id
            WHERE messages_fts MATCH ?
              AND messages_fts.user_id = ?
              AND m.user_id = ?
              AND m.sequence < (
                  SELECT sequence FROM messages WHERE id = ? AND user_id = ?
              )
            ORDER BY lexical_score ASC, m.sequence DESC
            LIMIT 100
            """,
            (candidate_query, user_id, user_id, newer_message_id, user_id),
        ).fetchall()
        superseded = select_superseded_message(
            content=content,
            occurred_at_ms=occurred_at_ms,
            candidates=[_stored_message(row) for row in rows],
        )
        if superseded is None:
            return
        connection.execute(
            """
            INSERT OR IGNORE INTO state_relations(
                newer_message_id, older_message_id, user_id, relation, created_at
            ) VALUES (?, ?, ?, 'supersedes', ?)
            """,
            (newer_message_id, superseded.id, user_id, created_at),
        )

    @staticmethod
    def _link_structured_state_update(
        connection: sqlite3.Connection,
        *,
        newer_message_id: str,
        user_id: str,
        facets: tuple[MemoryFacet, ...],
        created_at: str,
    ) -> None:
        values_by_kind: dict[str, set[str]] = {}
        for facet in facets:
            values_by_kind.setdefault(facet.kind, set()).add(facet.normalized_value)
        events = values_by_kind.get("event", set())
        dates = values_by_kind.get("date", set())
        statuses = values_by_kind.get("event_status", set())
        if not events or (not dates and not statuses):
            return
        anchors = set().union(
            events,
            values_by_kind.get("entity", set()),
            values_by_kind.get("alias", set()),
            values_by_kind.get("place", set()),
        )
        if not anchors:
            return
        placeholders = ", ".join("?" for _anchor in anchors)
        rows = connection.execute(
            f"""
            SELECT DISTINCT m.id, m.sequence
            FROM message_facets AS facet
            JOIN messages AS m ON m.id = facet.message_id
            WHERE facet.user_id = ?
              AND m.user_id = ?
              AND facet.normalized_value IN ({placeholders})
              AND m.sequence < (
                  SELECT sequence FROM messages WHERE id = ? AND user_id = ?
              )
            ORDER BY m.sequence DESC
            LIMIT 100
            """,
            (user_id, user_id, *sorted(anchors), newer_message_id, user_id),
        ).fetchall()
        best: tuple[int, int, str] | None = None
        for row in rows:
            candidate_id = str(row["id"])
            facet_rows = connection.execute(
                """
                SELECT kind, normalized_value
                FROM message_facets
                WHERE user_id = ? AND message_id = ?
                """,
                (user_id, candidate_id),
            ).fetchall()
            candidate_by_kind: dict[str, set[str]] = {}
            for facet_row in facet_rows:
                candidate_by_kind.setdefault(str(facet_row["kind"]), set()).add(
                    str(facet_row["normalized_value"])
                )
            shared_events = events.intersection(candidate_by_kind.get("event", set()))
            if not shared_events:
                continue
            shared_entities = values_by_kind.get("entity", set()).intersection(
                candidate_by_kind.get("entity", set())
            )
            shared_places = values_by_kind.get("place", set()).intersection(
                candidate_by_kind.get("place", set())
            )
            if not shared_entities and not shared_places:
                continue
            candidate_dates = candidate_by_kind.get("date", set())
            candidate_statuses = candidate_by_kind.get("event_status", set())
            if not statuses and dates == candidate_dates:
                continue
            score = (
                len(shared_events) * 4
                + len(shared_entities) * 2
                + len(shared_places)
                + (1 if statuses != candidate_statuses else 0)
            )
            candidate = (score, int(row["sequence"]), candidate_id)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            return
        connection.execute(
            """
            INSERT OR IGNORE INTO state_relations(
                newer_message_id, older_message_id, user_id, relation, created_at
            ) VALUES (?, ?, ?, 'supersedes', ?)
            """,
            (newer_message_id, best[2], user_id, created_at),
        )

    @staticmethod
    def _link_shared_facets(
        connection: sqlite3.Connection,
        *,
        newer_message_id: str,
        user_id: str,
        facets: tuple[MemoryFacet, ...],
        created_at: str,
    ) -> None:
        anchors = [
            facet
            for facet in facets
            if facet.kind in {"entity", "alias", "place"}
            and facet.confidence >= 0.8
            and len(facet.normalized_value) >= 3
        ]
        for facet in anchors:
            rows = connection.execute(
                """
                SELECT DISTINCT m.id
                FROM message_facets AS prior
                JOIN messages AS m ON m.id = prior.message_id
                WHERE prior.user_id = ?
                  AND m.user_id = ?
                  AND prior.normalized_value = ?
                  AND m.sequence < (
                      SELECT sequence FROM messages WHERE id = ? AND user_id = ?
                  )
                ORDER BY m.sequence DESC
                LIMIT 20
                """,
                (
                    user_id,
                    user_id,
                    facet.normalized_value,
                    newer_message_id,
                    user_id,
                ),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO memory_relations(
                        source_message_id, target_message_id, user_id, relation,
                        anchor, confidence, created_at
                    ) VALUES (?, ?, ?, 'shared_facet', ?, ?, ?)
                    """,
                    (
                        newer_message_id,
                        str(row["id"]),
                        user_id,
                        facet.normalized_value,
                        facet.confidence,
                        created_at,
                    ),
                )

    @staticmethod
    def _write_vectors(
        connection: sqlite3.Connection,
        *,
        message_ids: tuple[str, ...],
        user_id: str,
        embeddings: EmbeddingBatch,
        created_at: str,
    ) -> None:
        for message_id, vector in zip(message_ids, embeddings.vectors, strict=True):
            connection.execute(
                """
                INSERT INTO message_vectors(
                    message_id, user_id, model, dimensions, embedding, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    model = excluded.model,
                    dimensions = excluded.dimensions,
                    embedding = excluded.embedding,
                    created_at = excluded.created_at
                """,
                (
                    message_id,
                    user_id,
                    embeddings.model,
                    embeddings.dimensions,
                    _pack_vector(vector),
                    created_at,
                ),
            )

    def count_messages(self, *, user_id: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM messages"
        parameters: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters = (user_id,)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def count_state_relations(self, *, user_id: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM state_relations"
        parameters: tuple[Any, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters = (user_id,)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def count_message_tags(
        self,
        *,
        user_id: str | None = None,
        kind: MemoryTag | None = None,
    ) -> int:
        clauses: list[str] = []
        parameters: list[str] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            parameters.append(user_id)
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        query = "SELECT COUNT(*) AS count FROM message_tags"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self._connect() as connection:
            row = connection.execute(query, tuple(parameters)).fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def count_message_facets(self, *, user_id: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM message_facets"
        parameters: tuple[str, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters = (user_id,)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        assert row is not None
        return int(row["count"])

    def count_memory_relations(self, *, user_id: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM memory_relations"
        parameters: tuple[str, ...] = ()
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters = (user_id,)
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        assert row is not None
        return int(row["count"])

    def list_message_facets(
        self,
        *,
        user_id: str,
        message_ids: list[str],
    ) -> dict[str, tuple[MemoryFacet, ...]]:
        if not message_ids:
            return {}
        unique_ids = list(dict.fromkeys(message_ids))
        placeholders = ", ".join("?" for _message_id in unique_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT message_id, kind, value, normalized_value, confidence
                FROM message_facets
                WHERE user_id = ? AND message_id IN ({placeholders})
                ORDER BY message_id, kind, normalized_value
                """,
                (user_id, *unique_ids),
            ).fetchall()
        grouped: dict[str, list[MemoryFacet]] = {}
        for row in rows:
            message_id = str(row["message_id"])
            grouped.setdefault(message_id, []).append(
                MemoryFacet(
                    kind=cast(FacetKind, str(row["kind"])),
                    value=str(row["value"]),
                    normalized_value=str(row["normalized_value"]),
                    confidence=float(row["confidence"]),
                )
            )
        return {message_id: tuple(facets) for message_id, facets in grouped.items()}

    def list_diagnostic_relations(
        self,
        *,
        user_id: str,
        message_ids: list[str],
    ) -> list[MemoryRelation]:
        """Return bounded, user-isolated edges between recalled evidence items."""

        if not message_ids:
            return []
        unique_ids = list(dict.fromkeys(message_ids))
        placeholders = ", ".join("?" for _message_id in unique_ids)
        parameters = (user_id, *unique_ids, *unique_ids)
        with self._connect() as connection:
            state_rows = connection.execute(
                f"""
                SELECT newer_message_id AS source_id,
                       older_message_id AS target_id,
                       relation,
                       'state' AS anchor,
                       1.0 AS confidence
                FROM state_relations
                WHERE user_id = ?
                  AND newer_message_id IN ({placeholders})
                  AND older_message_id IN ({placeholders})
                """,
                parameters,
            ).fetchall()
            memory_rows = connection.execute(
                f"""
                SELECT source_message_id AS source_id,
                       target_message_id AS target_id,
                       relation,
                       anchor,
                       confidence
                FROM memory_relations
                WHERE user_id = ?
                  AND source_message_id IN ({placeholders})
                  AND target_message_id IN ({placeholders})
                ORDER BY confidence DESC, created_at DESC
                LIMIT 500
                """,
                parameters,
            ).fetchall()
        rows = [*state_rows, *memory_rows]
        relations = [
            MemoryRelation(
                source_id=str(row["source_id"]),
                target_id=str(row["target_id"]),
                relation=str(row["relation"]),
                anchor=str(row["anchor"]),
                confidence=float(row["confidence"]),
            )
            for row in rows
        ]
        relations.sort(
            key=lambda edge: (
                0 if edge.relation == "supersedes" else 1,
                edge.source_id,
                edge.target_id,
                edge.anchor,
            )
        )
        return relations[:500]

    def search_facets(
        self,
        *,
        user_id: str,
        facets: tuple[MemoryFacet, ...],
        limit: int,
    ) -> list[StoredMessage]:
        if limit <= 0 or not facets:
            return []
        pairs = list(
            dict.fromkeys((facet.kind, facet.normalized_value) for facet in facets)
        )
        predicates = " OR ".join(
            "(facet.kind = ? AND facet.normalized_value = ?)" for _pair in pairs
        )
        facet_parameters = [value for pair in pairs for value in pair]
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT m.sequence, m.id, m.request_id, m.user_id, m.session_id,
                       m.ordinal, m.role, m.occurred_at_ms, m.content, m.created_at,
                       COUNT(*) AS matched_facets,
                       MAX(facet.confidence) AS max_confidence
                FROM message_facets AS facet
                JOIN messages AS m ON m.id = facet.message_id
                WHERE facet.user_id = ?
                  AND m.user_id = ?
                  AND ({predicates})
                GROUP BY m.id
                ORDER BY matched_facets DESC,
                         max_confidence DESC,
                         m.occurred_at_ms IS NULL ASC,
                         m.occurred_at_ms DESC,
                         m.sequence DESC
                LIMIT ?
                """,
                (user_id, user_id, *facet_parameters, limit),
            ).fetchall()
        return [_stored_message(row) for row in rows]

    def list_forgotten_message_ids(
        self,
        *,
        user_id: str,
        message_ids: list[str],
    ) -> set[str]:
        if not message_ids:
            return set()
        unique_ids = list(dict.fromkeys(message_ids))
        placeholders = ", ".join("?" for _message_id in unique_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                WITH RECURSIVE forgotten(message_id) AS (
                    SELECT relation.older_message_id
                    FROM state_relations AS relation
                    JOIN message_facets AS facet
                      ON facet.message_id = relation.newer_message_id
                     AND facet.user_id = relation.user_id
                    WHERE relation.user_id = ?
                      AND facet.kind = 'event_status'
                      AND facet.normalized_value = 'forget'
                    UNION
                    SELECT relation.older_message_id
                    FROM state_relations AS relation
                    JOIN forgotten
                      ON forgotten.message_id = relation.newer_message_id
                    WHERE relation.user_id = ?
                )
                SELECT message_id
                FROM forgotten
                WHERE message_id IN ({placeholders})
                """,
                (user_id, user_id, *unique_ids),
            ).fetchall()
        return {str(row["message_id"]) for row in rows}

    def list_related_messages(
        self,
        *,
        user_id: str,
        message_ids: list[str],
        max_hops: int,
        limit: int,
    ) -> list[RelatedMessage]:
        if not message_ids or limit <= 0 or max_hops <= 0:
            return []
        max_hops = min(max_hops, 3)
        seed_ids = set(dict.fromkeys(message_ids))
        seen = set(seed_ids)
        frontier = set(seed_ids)
        related: dict[str, tuple[int, str]] = {}
        with self._connect() as connection:
            for hop in range(1, max_hops + 1):
                if not frontier or len(related) >= limit:
                    break
                frontier_values = sorted(frontier)
                placeholders = ", ".join("?" for _message_id in frontier_values)
                rows = connection.execute(
                    f"""
                    SELECT source_message_id, target_message_id, anchor
                    FROM memory_relations
                    WHERE user_id = ?
                      AND (
                          source_message_id IN ({placeholders})
                          OR target_message_id IN ({placeholders})
                      )
                    ORDER BY confidence DESC, created_at DESC
                    """,
                    (user_id, *frontier_values, *frontier_values),
                ).fetchall()
                next_frontier: set[str] = set()
                for row in rows:
                    source_id = str(row["source_message_id"])
                    target_id = str(row["target_message_id"])
                    candidate_id = target_id if source_id in frontier else source_id
                    if candidate_id in seen:
                        continue
                    seen.add(candidate_id)
                    next_frontier.add(candidate_id)
                    related[candidate_id] = (hop, str(row["anchor"]))
                    if len(related) >= limit:
                        break
                frontier = next_frontier
            if not related:
                return []
            selected_ids = list(related)
            selected_placeholders = ", ".join("?" for _message_id in selected_ids)
            message_rows = connection.execute(
                f"""
                SELECT sequence, id, request_id, user_id, session_id, ordinal,
                       role, occurred_at_ms, content, created_at
                FROM messages
                WHERE user_id = ? AND id IN ({selected_placeholders})
                """,
                (user_id, *selected_ids),
            ).fetchall()
        messages = {str(row["id"]): _stored_message(row) for row in message_rows}
        ranked = [
            RelatedMessage(message=messages[message_id], hop=hop, anchor=anchor)
            for message_id, (hop, anchor) in related.items()
            if message_id in messages
        ]
        ranked.sort(key=lambda item: (item.hop, -item.message.sequence))
        return ranked[:limit]

    def list_messages(self, *, user_id: str) -> list[StoredMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, id, request_id, user_id, session_id, ordinal,
                       role, occurred_at_ms, content, created_at
                FROM messages
                WHERE user_id = ?
                ORDER BY sequence
                """,
                (user_id,),
            ).fetchall()
        return [_stored_message(row) for row in rows]

    def list_session_messages(self, *, user_id: str, session_id: str) -> list[StoredMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, id, request_id, user_id, session_id, ordinal,
                       role, occurred_at_ms, content, created_at
                FROM messages
                WHERE user_id = ? AND session_id = ?
                ORDER BY sequence
                """,
                (user_id, session_id),
            ).fetchall()
        return [_stored_message(row) for row in rows]

    def list_state_chain(
        self,
        *,
        user_id: str,
        message_ids: list[str],
        limit: int,
    ) -> list[StoredMessage]:
        """Return a bounded, same-user supersession component newest first."""

        if limit <= 0 or not message_ids:
            return []
        unique_ids = list(dict.fromkeys(message_ids))
        with self._connect() as connection:
            seed_placeholders = ", ".join("?" for _message_id in unique_ids)
            seed_rows = connection.execute(
                f"""
                SELECT id
                FROM messages
                WHERE user_id = ? AND id IN ({seed_placeholders})
                """,
                (user_id, *unique_ids),
            ).fetchall()
            seen = {str(row["id"]) for row in seed_rows}
            frontier = set(seen)
            for _depth in range(8):
                if not frontier or len(seen) >= limit:
                    break
                frontier_values = sorted(frontier)
                placeholders = ", ".join("?" for _message_id in frontier_values)
                relation_rows = connection.execute(
                    f"""
                    SELECT newer_message_id, older_message_id
                    FROM state_relations
                    WHERE user_id = ?
                      AND (
                          newer_message_id IN ({placeholders})
                          OR older_message_id IN ({placeholders})
                      )
                    """,
                    (user_id, *frontier_values, *frontier_values),
                ).fetchall()
                connected = {
                    str(row[column])
                    for row in relation_rows
                    for column in ("newer_message_id", "older_message_id")
                }
                frontier = connected.difference(seen)
                seen.update(frontier)

            if not seen:
                return []
            selected_ids = sorted(seen)[:limit]
            selected_placeholders = ", ".join("?" for _message_id in selected_ids)
            rows = connection.execute(
                f"""
                SELECT sequence, id, request_id, user_id, session_id, ordinal,
                       role, occurred_at_ms, content, created_at
                FROM messages
                WHERE user_id = ? AND id IN ({selected_placeholders})
                ORDER BY occurred_at_ms IS NULL ASC,
                         occurred_at_ms DESC,
                         sequence DESC
                LIMIT ?
                """,
                (user_id, *selected_ids, limit),
            ).fetchall()
        return [_stored_message(row) for row in rows]

    def list_tagged_messages(
        self,
        *,
        user_id: str,
        kind: MemoryTag,
        limit: int,
    ) -> list[StoredMessage]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.sequence, m.id, m.request_id, m.user_id, m.session_id,
                       m.ordinal, m.role, m.occurred_at_ms, m.content, m.created_at
                FROM message_tags AS tag
                JOIN messages AS m ON m.id = tag.message_id
                WHERE tag.user_id = ?
                  AND m.user_id = ?
                  AND tag.kind = ?
                ORDER BY m.occurred_at_ms IS NULL ASC,
                         m.occurred_at_ms DESC,
                         m.sequence DESC
                LIMIT ?
                """,
                (user_id, user_id, kind, limit),
            ).fetchall()
        return [_stored_message(row) for row in rows]

    def search_fts(
        self, *, user_id: str, fts_query: str, limit: int
    ) -> list[tuple[StoredMessage, float]]:
        """Return lexical candidates after enforcing user isolation twice."""

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT m.sequence, m.id, m.request_id, m.user_id, m.session_id,
                       m.ordinal, m.role, m.occurred_at_ms, m.content, m.created_at,
                       bm25(messages_fts) AS lexical_score
                FROM messages_fts
                JOIN messages AS m ON m.id = messages_fts.message_id
                WHERE messages_fts MATCH ?
                  AND messages_fts.user_id = ?
                  AND m.user_id = ?
                ORDER BY lexical_score ASC, m.sequence ASC
                LIMIT ?
                """,
                (fts_query, user_id, user_id, limit),
            ).fetchall()
        return [(_stored_message(row), float(row["lexical_score"])) for row in rows]

    def search_vectors(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        model: str,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> list[tuple[StoredMessage, float]]:
        """Rank the current user's compatible stored vectors by cosine similarity."""

        if limit <= 0:
            return []
        if not query_vector:
            raise ValueError("query vector must not be empty")
        if not all(math.isfinite(value) for value in query_vector):
            raise ValueError("query vector must contain only finite values")
        if not any(value != 0.0 for value in query_vector):
            raise ValueError("query vector must not be a zero vector")

        dimensions = len(query_vector)
        session_clause = "" if session_id is None else " AND m.session_id = ?"
        parameters: tuple[object, ...] = (user_id, user_id, model, dimensions)
        if session_id is not None:
            parameters = (*parameters, session_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT m.sequence, m.id, m.request_id, m.user_id, m.session_id,
                       m.ordinal, m.role, m.occurred_at_ms, m.content, m.created_at,
                       v.embedding
                FROM message_vectors AS v
                JOIN messages AS m ON m.id = v.message_id
                WHERE v.user_id = ?
                  AND m.user_id = ?
                  AND v.model = ?
                  AND v.dimensions = ?
                  {session_clause}
                """,
                parameters,
            ).fetchall()

        ranked = [
            (
                _stored_message(row),
                _cosine_similarity(
                    query_vector,
                    _unpack_vector(bytes(row["embedding"]), dimensions),
                ),
            )
            for row in rows
        ]
        ranked.sort(key=lambda item: (-item[1], item[0].sequence))
        return ranked[:limit]
