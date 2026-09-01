"""Strict request and response models for the leaderboard contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class ContractModel(BaseModel):
    """Base model that rejects accidental protocol extensions."""

    model_config = ConfigDict(extra="forbid")


class MessageInput(ContractModel):
    role: Literal["user", "assistant"]
    timestamp: Annotated[int, Field(ge=0)] | None = None
    content: str

    _content_not_blank = field_validator("content")(_require_non_blank)


class AddRequest(ContractModel):
    request_id: str
    messages: Annotated[list[MessageInput], Field(min_length=1)]
    user_id: str
    session_id: str

    _identifiers_not_blank = field_validator(
        "request_id", "user_id", "session_id"
    )(_require_non_blank)


class AddResponse(ContractModel):
    success: Literal[True] = True
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(ContractModel):
    query: str
    options: list[str] | None = None
    user_id: str
    top_k: Annotated[int, Field(ge=1, le=100)]

    _query_and_user_not_blank = field_validator("query", "user_id")(_require_non_blank)

    @field_validator("options")
    @classmethod
    def options_must_not_contain_blanks(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for option in value:
                _require_non_blank(option)
        return value


class MemoryEvidence(ContractModel):
    id: str
    content: str
    score: float | None = None
    created_at: datetime | None = None


class SearchResponse(ContractModel):
    data: list[MemoryEvidence]
