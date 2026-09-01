"""SQLite persistence with transactional Add semantics."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_memory.errors import RequestConflictError
from aml_memory.models import AddResult, StoredMessage
from aml_memory.schemas import AddRequest

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

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    message_id UNINDEXED,
    user_id UNINDEXED,
    content,
    tokenize = 'unicode61'
);
"""


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
            connection.commit()

    def check(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def add(self, request: AddRequest) -> AddResult:
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
                        (memory_id, request.user_id, message.content),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

        return AddResult(inserted=True, message_ids=message_ids)

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
