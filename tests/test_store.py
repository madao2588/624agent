from pathlib import Path

import pytest

from aml_memory.errors import RequestConflictError
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
