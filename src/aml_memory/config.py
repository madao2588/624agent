"""Runtime configuration for the memory service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True, slots=True)
class EvaluationProfile:
    """Frozen, machine-readable settings for a reproducible leaderboard run."""

    schema_version: int = 1
    model: str = "gpt-4o-mini"
    add_enrichment: bool = True
    search_planning: bool = True
    external_failure: Literal["fail-closed"] = "fail-closed"
    graph_hops: int = 3
    lexical_candidate_limit: int = 400
    facet_candidate_limit: int = 200
    relevance_threshold: float = 0.18
    provider_timeout_seconds: float = 30.0
    provider_max_attempts: int = 2
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("evaluation profile schema_version must be 1")
        if self.model != "gpt-4o-mini":
            raise ValueError("evaluation profile model must be gpt-4o-mini")
        if not self.add_enrichment or not self.search_planning:
            raise ValueError("evaluation profile must enable Add and Search model use")
        if self.external_failure != "fail-closed":
            raise ValueError("evaluation profile external_failure must be fail-closed")
        if not 1 <= self.graph_hops <= 3:
            raise ValueError("evaluation profile graph_hops must be between 1 and 3")
        if self.lexical_candidate_limit <= 0 or self.facet_candidate_limit <= 0:
            raise ValueError("evaluation profile candidate limits must be positive")
        if not 0.0 <= self.relevance_threshold <= 1.0:
            raise ValueError("evaluation profile relevance_threshold must be between 0 and 1")
        if self.provider_timeout_seconds <= 0:
            raise ValueError("evaluation profile provider_timeout_seconds must be positive")
        if self.provider_max_attempts <= 0:
            raise ValueError("evaluation profile provider_max_attempts must be positive")
        if self.circuit_failure_threshold <= 0:
            raise ValueError(
                "evaluation profile circuit_failure_threshold must be positive"
            )
        if self.circuit_cooldown_seconds <= 0:
            raise ValueError(
                "evaluation profile circuit_cooldown_seconds must be positive"
            )

    @classmethod
    def from_path(cls, path: str | Path) -> EvaluationProfile:
        profile_path = Path(path)
        try:
            payload: object = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"could not load evaluation profile: {profile_path}") from error
        if not isinstance(payload, dict):
            raise ValueError("evaluation profile must be a JSON object")
        values = cast(dict[str, object], payload)

        def require_int(name: str) -> int:
            value = values.get(name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"evaluation profile {name} must be an integer")
            return value

        def require_float(name: str) -> float:
            value = values.get(name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"evaluation profile {name} must be numeric")
            return float(value)

        def require_bool(name: str) -> bool:
            value = values.get(name)
            if not isinstance(value, bool):
                raise ValueError(f"evaluation profile {name} must be a boolean")
            return value

        def require_string(name: str) -> str:
            value = values.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"evaluation profile {name} must be a non-empty string")
            return value

        external_failure = require_string("external_failure")
        if external_failure != "fail-closed":
            raise ValueError("evaluation profile external_failure must be fail-closed")
        return cls(
            schema_version=require_int("schema_version"),
            model=require_string("model"),
            add_enrichment=require_bool("add_enrichment"),
            search_planning=require_bool("search_planning"),
            external_failure="fail-closed",
            graph_hops=require_int("graph_hops"),
            lexical_candidate_limit=require_int("lexical_candidate_limit"),
            facet_candidate_limit=require_int("facet_candidate_limit"),
            relevance_threshold=require_float("relevance_threshold"),
            provider_timeout_seconds=require_float("provider_timeout_seconds"),
            provider_max_attempts=require_int("provider_max_attempts"),
            circuit_failure_threshold=require_int("circuit_failure_threshold"),
            circuit_cooldown_seconds=require_float("circuit_cooldown_seconds"),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings with deterministic local defaults."""

    database_path: Path
    runtime_mode: str = "local"
    neighbor_radius: int = 1
    auth_scheme: str = "none"
    api_key: str | None = None
    embedding_provider: str = "none"
    embedding_api_key: str | None = field(default=None, repr=False)
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_dimensions: int | None = None
    embedding_timeout_seconds: float = 30.0
    evaluation_api_key: str | None = field(default=None, repr=False)
    evaluation_model: str = "gpt-4o-mini"
    evaluation_profile: EvaluationProfile | None = None

    def __post_init__(self) -> None:
        runtime_mode = self.runtime_mode.strip().lower()
        if runtime_mode not in {"local", "evaluation"}:
            raise ValueError("MEMORY_RUNTIME_MODE must be local or evaluation")
        object.__setattr__(self, "runtime_mode", runtime_mode)
        has_evaluation_key = self.evaluation_api_key is not None and bool(
            self.evaluation_api_key.strip()
        )
        if runtime_mode == "evaluation":
            if not has_evaluation_key:
                raise ValueError(
                    "MEMORY_EVALUATION_API_KEY is required in evaluation mode"
                )
            if self.evaluation_model != "gpt-4o-mini":
                raise ValueError("evaluation mode requires gpt-4o-mini")
            profile = self.evaluation_profile or EvaluationProfile()
            if profile.model != self.evaluation_model:
                raise ValueError("evaluation model must match the frozen profile")
            object.__setattr__(self, "evaluation_profile", profile)
        elif has_evaluation_key or self.evaluation_profile is not None:
            raise ValueError(
                "evaluation credentials and profile require MEMORY_RUNTIME_MODE=evaluation"
            )

        scheme = self.auth_scheme.strip().lower()
        if scheme not in {"none", "token", "bearer", "x-api-key"}:
            raise ValueError("MEMORY_AUTH_SCHEME must be none, token, bearer, or x-api-key")
        object.__setattr__(self, "auth_scheme", scheme)

        has_key = self.api_key is not None and bool(self.api_key.strip())
        if scheme == "none" and has_key:
            raise ValueError("MEMORY_API_KEY requires an enabled MEMORY_AUTH_SCHEME")
        if scheme != "none" and not has_key:
            raise ValueError("MEMORY_API_KEY is required when API authentication is enabled")

        provider = self.embedding_provider.strip().lower()
        if provider not in {"none", "openai-compatible"}:
            raise ValueError(
                "MEMORY_EMBEDDING_PROVIDER must be none or openai-compatible"
            )
        object.__setattr__(self, "embedding_provider", provider)
        has_embedding_key = self.embedding_api_key is not None and bool(
            self.embedding_api_key.strip()
        )
        if provider == "none" and has_embedding_key:
            raise ValueError(
                "MEMORY_EMBEDDING_API_KEY requires an enabled MEMORY_EMBEDDING_PROVIDER"
            )
        if provider != "none" and not has_embedding_key:
            raise ValueError(
                "MEMORY_EMBEDDING_API_KEY is required when embeddings are enabled"
            )
        if provider != "none" and not self.embedding_model.strip():
            raise ValueError("MEMORY_EMBEDDING_MODEL must not be blank")
        if provider != "none" and not self.embedding_base_url.strip():
            raise ValueError("MEMORY_EMBEDDING_BASE_URL must not be blank")
        if self.embedding_dimensions is not None and self.embedding_dimensions <= 0:
            raise ValueError("MEMORY_EMBEDDING_DIMENSIONS must be positive")
        if self.embedding_timeout_seconds <= 0:
            raise ValueError("MEMORY_EMBEDDING_TIMEOUT_SECONDS must be positive")

    @classmethod
    def from_environment(cls) -> Settings:
        dimensions = os.getenv("MEMORY_EMBEDDING_DIMENSIONS")
        runtime_mode = os.getenv("MEMORY_RUNTIME_MODE", "local")
        evaluation_profile = None
        if runtime_mode.strip().lower() == "evaluation":
            evaluation_profile = EvaluationProfile.from_path(
                os.getenv(
                    "MEMORY_EVALUATION_PROFILE",
                    "evaluation/evaluation-profile.json",
                )
            )
        return cls(
            database_path=Path(os.getenv("MEMORY_DB_PATH", "data/memory.db")),
            runtime_mode=runtime_mode,
            neighbor_radius=int(os.getenv("MEMORY_NEIGHBOR_RADIUS", "1")),
            auth_scheme=os.getenv("MEMORY_AUTH_SCHEME", "none"),
            api_key=os.getenv("MEMORY_API_KEY") or None,
            embedding_provider=os.getenv("MEMORY_EMBEDDING_PROVIDER", "none"),
            embedding_api_key=os.getenv("MEMORY_EMBEDDING_API_KEY") or None,
            embedding_model=os.getenv(
                "MEMORY_EMBEDDING_MODEL", "text-embedding-3-small"
            ),
            embedding_base_url=os.getenv(
                "MEMORY_EMBEDDING_BASE_URL", "https://api.openai.com/v1"
            ),
            embedding_dimensions=int(dimensions) if dimensions else None,
            embedding_timeout_seconds=float(
                os.getenv("MEMORY_EMBEDDING_TIMEOUT_SECONDS", "30")
            ),
            evaluation_api_key=os.getenv("MEMORY_EVALUATION_API_KEY") or None,
            evaluation_model=os.getenv("MEMORY_EVALUATION_MODEL", "gpt-4o-mini"),
            evaluation_profile=evaluation_profile,
        )
