"""Strict request and response models for the leaderboard contract."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from aml_memory.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    LOCAL_EMBEDDING_BASE_URL,
)


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


class DiagnosticFacet(ContractModel):
    kind: str
    value: str
    normalized_value: str
    confidence: float


class DiagnosticMemoryEvidence(MemoryEvidence):
    reasons: list[str]
    facets: list[DiagnosticFacet]
    state: Literal["active", "history", "cancelled", "forgotten"]


class DiagnosticRelation(ContractModel):
    source_id: str
    target_id: str
    relation: str
    anchor: str
    confidence: float


class SearchDiagnosticsResponse(ContractModel):
    data: list[DiagnosticMemoryEvidence]
    relations: list[DiagnosticRelation]


class RetrievalConnectionCreate(ContractModel):
    provider: Literal["local", "openai", "openai-compatible", "deepseek"]
    api_key: SecretStr | None = None
    model: str | None = None
    base_url: str | None = None

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None:
            _require_non_blank(value)
        return value

    @field_validator("api_key")
    @classmethod
    def api_key_must_not_be_blank(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            _require_non_blank(value.get_secret_value())
        return value

    @model_validator(mode="after")
    def validate_provider_url(self) -> RetrievalConnectionCreate:
        if self.provider == "local":
            if self.api_key is not None:
                raise ValueError("local provider does not accept an API key")
            if self.base_url is not None:
                raise ValueError("local provider does not accept a base_url")
            if self.model not in {None, DEFAULT_LOCAL_EMBEDDING_MODEL}:
                raise ValueError("local provider uses the allowlisted local model")
            return self
        if self.api_key is None:
            raise ValueError("API key is required for an external provider")
        if self.provider == "openai":
            if self.base_url not in {None, "https://api.openai.com/v1"}:
                raise ValueError("OpenAI provider uses https://api.openai.com/v1")
            return self
        if self.provider == "deepseek":
            if self.base_url not in {None, "https://api.deepseek.com"}:
                raise ValueError("DeepSeek provider uses https://api.deepseek.com")
            return self
        if self.model is None:
            raise ValueError("model is required for an OpenAI-compatible provider")
        if self.base_url is None:
            raise ValueError("base_url is required for an OpenAI-compatible provider")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an HTTP(S) URL with a hostname")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain a query or fragment")
        return self

    @property
    def resolved_base_url(self) -> str:
        if self.provider == "local":
            return LOCAL_EMBEDDING_BASE_URL
        if self.provider == "openai":
            return "https://api.openai.com/v1"
        if self.provider == "deepseek":
            return "https://api.deepseek.com"
        assert self.base_url is not None
        return self.base_url.rstrip("/")

    @property
    def resolved_model(self) -> str:
        if self.model is not None:
            return self.model
        if self.provider == "local":
            return DEFAULT_LOCAL_EMBEDDING_MODEL
        if self.provider == "deepseek":
            return "deepseek-v4-flash"
        return "text-embedding-3-small"


EmbeddingConnectionCreate = RetrievalConnectionCreate


class EmbeddingConnectionResponse(ContractModel):
    connection_id: str
    provider: Literal["local", "openai", "openai-compatible", "deepseek"]
    model: str
    base_url: str
    expires_at: datetime


class EmbeddingConnectionDeleteResponse(ContractModel):
    success: Literal[True] = True


class RetrievalConnectionResponse(ContractModel):
    connection_id: str
    provider: Literal["local", "openai", "openai-compatible", "deepseek"]
    capability: Literal["embedding", "query-expansion"]
    model: str
    base_url: str
    expires_at: datetime


RetrievalConnectionDeleteResponse = EmbeddingConnectionDeleteResponse
