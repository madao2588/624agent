import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aml_memory.errors import RequestConflictError
from aml_memory.models import EmbeddingBatch
from aml_memory.schemas import AddRequest, MessageInput
from aml_memory.store import MemoryStore


def make_request(
    *,
    request_id: str = "request-1",
    user_id: str = "user-1",
    session_id: str = "session-1",
    content: str = "I adopted a cat named Luna.",
) -> AddRequest:
    return AddRequest(
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        messages=[
            MessageInput(role="user", timestamp=1_704_067_200_000, content=content),
            MessageInput(role="assistant", timestamp=1_704_067_201_000, content="Noted."),
        ],
    )


def test_add_persists_original_messages_across_store_instances(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    first_store = MemoryStore(database_path)
    first_store.initialize()

    result = first_store.add(make_request())

    assert result.inserted is True
    original_ids = result.message_ids
    assert first_store.count_messages(user_id="user-1") == 2

    reopened_store = MemoryStore(database_path)
    reopened_store.initialize()
    messages = reopened_store.list_messages(user_id="user-1")

    assert [message.id for message in messages] == list(original_ids)
    assert [message.content for message in messages] == [
        "I adopted a cat named Luna.",
        "Noted.",
    ]


def test_repeating_identical_add_is_idempotent(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    request = make_request()

    first = store.add(request)
    repeated = store.add(request)

    assert first.inserted is True
    assert repeated.inserted is False
    assert repeated.message_ids == first.message_ids
    assert store.count_messages() == 2


def test_reusing_request_id_with_different_payload_conflicts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    store.add(make_request())

    with pytest.raises(RequestConflictError):
        store.add(make_request(content="This is a different payload."))

    assert store.count_messages() == 2


def test_users_with_identical_content_remain_separate(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    store.add(make_request(request_id="request-a", user_id="user-a"))
    store.add(make_request(request_id="request-b", user_id="user-b"))

    assert store.count_messages(user_id="user-a") == 2
    assert store.count_messages(user_id="user-b") == 2
    assert {message.user_id for message in store.list_messages(user_id="user-a")} == {
        "user-a"
    }


def test_vectors_persist_across_store_instances_and_enforce_user_isolation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    user_a = make_request(
        request_id="request-vector-a",
        user_id="user-a",
        content="I spend free weekends cycling outside the city.",
    )
    user_b = make_request(
        request_id="request-vector-b",
        user_id="user-b",
        content="User B has a private cycling note.",
    )
    store.add(
        user_a,
        embeddings=EmbeddingBatch(
            model="semantic-test",
            vectors=((1.0, 0.0), (0.0, 1.0)),
        ),
    )
    store.add(
        user_b,
        embeddings=EmbeddingBatch(
            model="semantic-test",
            vectors=((1.0, 0.0), (0.0, 1.0)),
        ),
    )

    reopened = MemoryStore(database_path)
    reopened.initialize()
    hits = reopened.search_vectors(
        user_id="user-a",
        model="semantic-test",
        query_vector=(1.0, 0.0),
        limit=10,
    )

    assert hits
    assert hits[0][0].content == "I spend free weekends cycling outside the city."
    assert {message.user_id for message, _score in hits} == {"user-a"}


def test_invalid_embedding_batch_does_not_partially_write_add(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()

    with pytest.raises(ValueError, match="one vector per message"):
        store.add(
            make_request(),
            embeddings=EmbeddingBatch(
                model="semantic-test",
                vectors=((1.0, 0.0),),
            ),
        )

    assert store.count_messages() == 0


def test_explicit_update_persists_a_user_isolated_state_chain(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    old_result = store.add(
        AddRequest(
            request_id="request-old-state",
            user_id="user-a",
            session_id="session-old-state",
            messages=[
                MessageInput(
                    role="user",
                    timestamp=1_704_067_200_000,
                    content="The Atlas launch briefing is Friday morning in Room 8.",
                )
            ],
        )
    )
    new_request = AddRequest(
        request_id="request-new-state",
        user_id="user-a",
        session_id="session-new-state",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_153_600_000,
                content=(
                    "The Atlas briefing has been rescheduled to Monday afternoon "
                    "in Room 12."
                ),
            )
        ],
    )
    new_result = store.add(new_request)
    repeated = store.add(new_request)

    reopened = MemoryStore(database_path)
    reopened.initialize()
    chain = reopened.list_state_chain(
        user_id="user-a",
        message_ids=[old_result.message_ids[0]],
        limit=10,
    )

    assert repeated.inserted is False
    assert repeated.message_ids == new_result.message_ids
    assert reopened.count_state_relations(user_id="user-a") == 1
    assert [message.content for message in chain] == [
        "The Atlas briefing has been rescheduled to Monday afternoon in Room 12.",
        "The Atlas launch briefing is Friday morning in Room 8.",
    ]
    assert (
        reopened.list_state_chain(
            user_id="user-b",
            message_ids=[old_result.message_ids[0]],
            limit=10,
        )
        == []
    )


def test_weak_topic_overlap_does_not_create_a_state_relation(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    store.add(
        AddRequest(
            request_id="request-budget",
            user_id="user-1",
            session_id="session-budget",
            messages=[
                MessageInput(
                    role="user",
                    content="The Atlas marketing budget is awaiting approval.",
                )
            ],
        )
    )
    store.add(
        AddRequest(
            request_id="request-launch",
            user_id="user-1",
            session_id="session-launch",
            messages=[
                MessageInput(
                    role="user",
                    content="The Atlas launch moved to the north auditorium.",
                )
            ],
        )
    )

    assert store.count_state_relations(user_id="user-1") == 0


def test_explicit_memory_tags_are_idempotent_and_user_isolated(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    request = AddRequest(
        request_id="request-tagged-sources",
        user_id="user-a",
        session_id="session-tagged-sources",
        messages=[
            MessageInput(
                role="user",
                content="I always choose quiet corner tables and avoid loud rooms.",
            ),
            MessageInput(
                role="assistant",
                content="Restore frozen tickets before editing them; never modify them in place.",
            ),
            MessageInput(role="user", content="The parcel arrived at noon."),
        ],
    )

    first = store.add(request)
    repeated = store.add(request)
    reopened = MemoryStore(database_path)
    reopened.initialize()

    assert first.inserted is True
    assert repeated.inserted is False
    assert reopened.count_message_tags(user_id="user-a") == 2
    assert [
        message.content
        for message in reopened.list_tagged_messages(
            user_id="user-a",
            kind="preference",
            limit=10,
        )
    ] == ["I always choose quiet corner tables and avoid loud rooms."]
    assert [
        message.content
        for message in reopened.list_tagged_messages(
            user_id="user-a",
            kind="procedure",
            limit=10,
        )
    ] == [
        "Restore frozen tickets before editing them; never modify them in place."
    ]
    assert (
        reopened.list_tagged_messages(
            user_id="user-b",
            kind="preference",
            limit=10,
        )
        == []
    )


def test_initialize_backfills_tags_for_sources_written_before_the_tag_migration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    store.add(
        AddRequest(
            request_id="request-before-tag-migration",
            user_id="user-1",
            session_id="session-before-tag-migration",
            messages=[
                MessageInput(role="user", content="I prefer quiet reading rooms.")
            ],
        )
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM message_tags")
        connection.execute(
            "DELETE FROM schema_metadata WHERE key = 'message_tags_backfill_v1'"
        )
        connection.commit()

    reopened = MemoryStore(database_path)
    reopened.initialize()

    assert reopened.count_message_tags(user_id="user-1", kind="preference") == 1


def test_structured_facets_are_idempotent_durable_and_user_isolated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    request = AddRequest(
        request_id="request-structured-facets",
        user_id="user-a",
        session_id="session-structured-facets",
        messages=[
            MessageInput(
                role="user",
                timestamp=round(
                    datetime(2026, 9, 1, 9, tzinfo=UTC).timestamp() * 1000
                ),
                content="Omar works with me on Atlas.",
            ),
            MessageInput(
                role="assistant",
                content="He recommended Juniper Cafe for the meeting tomorrow.",
            ),
        ],
    )

    first = store.add(request)
    repeated = store.add(request)
    reopened = MemoryStore(database_path)
    reopened.initialize()
    facets = reopened.list_message_facets(
        user_id="user-a",
        message_ids=list(first.message_ids),
    )

    assert repeated.inserted is False
    assert reopened.count_message_facets(user_id="user-a") >= 5
    second_values = {
        facet.normalized_value for facet in facets[first.message_ids[1]]
    }
    assert {"omar", "juniper cafe"} <= second_values
    assert (
        reopened.list_message_facets(
            user_id="user-b",
            message_ids=list(first.message_ids),
        )
        == {}
    )


def test_initialize_backfills_structured_facets_for_existing_messages(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    store = MemoryStore(database_path)
    store.initialize()
    result = store.add(
        AddRequest(
            request_id="request-before-facet-migration",
            user_id="user-1",
            session_id="session-before-facet-migration",
            messages=[
                MessageInput(
                    role="user",
                    content="Professor Lin also known as 林老师 prefers West Lake.",
                )
            ],
        )
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM message_facets")
        connection.execute(
            "DELETE FROM schema_metadata WHERE key = 'message_facets_backfill_v1'"
        )
        connection.commit()

    reopened = MemoryStore(database_path)
    reopened.initialize()
    facets = reopened.list_message_facets(
        user_id="user-1",
        message_ids=list(result.message_ids),
    )

    assert {facet.kind for facet in facets[result.message_ids[0]]} >= {
        "entity",
        "alias",
        "place",
        "preference",
    }
