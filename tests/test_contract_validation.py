from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aml_memory.schemas import (
    AddRequest,
    AddResponse,
    MemoryEvidence,
    MessageInput,
    SearchRequest,
    SearchResponse,
)


def test_valid_add_contract_round_trips_required_identifiers() -> None:
    request = AddRequest(
        request_id="request-1",
        user_id="user-1",
        session_id="session-1",
        messages=[MessageInput(role="user", timestamp=1_704_067_200_000, content="hello")],
    )

    response = AddResponse(
        success=True,
        request_id=request.request_id,
        user_id=request.user_id,
        session_id=request.session_id,
    )

    assert response.model_dump() == {
        "success": True,
        "request_id": "request-1",
        "user_id": "user-1",
        "session_id": "session-1",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", " "),
        ("user_id", ""),
        ("session_id", "\t"),
    ],
)
def test_add_rejects_blank_identifiers(field: str, value: str) -> None:
    payload = {
        "request_id": "request-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "messages": [{"role": "user", "content": "hello"}],
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        AddRequest.model_validate(payload)


def test_add_rejects_empty_messages_and_invalid_roles() -> None:
    with pytest.raises(ValidationError):
        AddRequest(
            request_id="request-1",
            user_id="user-1",
            session_id="session-1",
            messages=[],
        )

    with pytest.raises(ValidationError):
        MessageInput.model_validate({"role": "system", "content": "hidden"})


def test_message_rejects_blank_content_without_rewriting_original_content() -> None:
    with pytest.raises(ValidationError):
        MessageInput(role="user", content=" \n\t")

    message = MessageInput(role="assistant", content="  preserve my spacing  ")
    assert message.content == "  preserve my spacing  "


@pytest.mark.parametrize("top_k", [0, 101])
def test_search_rejects_top_k_outside_platform_range(top_k: int) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="where?", user_id="user-1", top_k=top_k)


def test_search_response_uses_required_data_wrapper() -> None:
    response = SearchResponse(
        data=[
            MemoryEvidence(
                id="memory-1",
                content="[2024-01-01T00:00:00Z] USER: hello",
                score=1.0,
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        ]
    )

    dumped = response.model_dump(mode="json")
    assert list(dumped) == ["data"]
    assert dumped["data"][0]["id"] == "memory-1"
