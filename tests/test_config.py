from pathlib import Path

import pytest

from aml_memory.config import EvaluationProfile, Settings


def test_embedding_configuration_is_disabled_by_default(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "memory.db")

    assert settings.embedding_provider == "none"
    assert settings.embedding_api_key is None


def test_enabled_embedding_provider_requires_a_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MEMORY_EMBEDDING_API_KEY"):
        Settings(
            database_path=tmp_path / "memory.db",
            embedding_provider="openai-compatible",
        )


def test_embedding_environment_configuration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.setenv("MEMORY_EMBEDDING_API_KEY", "secret")
    monkeypatch.setenv("MEMORY_EMBEDDING_MODEL", "text-embedding-test")
    monkeypatch.setenv("MEMORY_EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("MEMORY_EMBEDDING_DIMENSIONS", "256")
    monkeypatch.setenv("MEMORY_EMBEDDING_TIMEOUT_SECONDS", "12.5")

    settings = Settings.from_environment()

    assert settings.embedding_provider == "openai-compatible"
    assert settings.embedding_api_key == "secret"
    assert settings.embedding_model == "text-embedding-test"
    assert settings.embedding_base_url == "https://embedding.example/v1"
    assert settings.embedding_dimensions == 256
    assert settings.embedding_timeout_seconds == 12.5


def test_local_mode_is_the_free_deterministic_default(tmp_path: Path) -> None:
    settings = Settings(database_path=tmp_path / "memory.db")

    assert settings.runtime_mode == "local"
    assert settings.evaluation_api_key is None
    assert settings.evaluation_profile is None


def test_evaluation_mode_requires_its_model_credential(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MEMORY_EVALUATION_API_KEY"):
        Settings(
            database_path=tmp_path / "memory.db",
            runtime_mode="evaluation",
        )


def test_evaluation_mode_rejects_a_model_that_differs_from_the_frozen_profile(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="gpt-4o-mini"):
        Settings(
            database_path=tmp_path / "memory.db",
            runtime_mode="evaluation",
            evaluation_api_key="secret",
            evaluation_model="another-model",
        )


def test_evaluation_profile_loads_the_frozen_retrieval_limits(tmp_path: Path) -> None:
    profile_path = tmp_path / "evaluation-profile.json"
    profile_path.write_text(
        """
        {
          "schema_version": 1,
          "model": "gpt-4o-mini",
          "add_enrichment": true,
          "search_planning": true,
          "external_failure": "fail-closed",
          "graph_hops": 3,
          "lexical_candidate_limit": 400,
          "facet_candidate_limit": 200,
          "relevance_threshold": 0.18,
          "provider_timeout_seconds": 30.0,
          "provider_max_attempts": 2,
          "circuit_failure_threshold": 3,
          "circuit_cooldown_seconds": 30.0
        }
        """,
        encoding="utf-8",
    )

    profile = EvaluationProfile.from_path(profile_path)

    assert profile.model == "gpt-4o-mini"
    assert profile.graph_hops == 3
    assert profile.facet_candidate_limit == 200
    assert profile.external_failure == "fail-closed"
    assert profile.provider_max_attempts == 2
    assert profile.circuit_failure_threshold == 3
    assert profile.circuit_cooldown_seconds == 30.0


def test_evaluation_environment_loads_the_checked_profile(
    monkeypatch, tmp_path: Path
) -> None:
    profile_path = tmp_path / "evaluation-profile.json"
    profile_path.write_text(
        """
        {
          "schema_version": 1,
          "model": "gpt-4o-mini",
          "add_enrichment": true,
          "search_planning": true,
          "external_failure": "fail-closed",
          "graph_hops": 3,
          "lexical_candidate_limit": 400,
          "facet_candidate_limit": 200,
          "relevance_threshold": 0.18,
          "provider_timeout_seconds": 30.0,
          "provider_max_attempts": 2,
          "circuit_failure_threshold": 3,
          "circuit_cooldown_seconds": 30.0
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("MEMORY_RUNTIME_MODE", "evaluation")
    monkeypatch.setenv("MEMORY_EVALUATION_API_KEY", "secret")
    monkeypatch.setenv("MEMORY_EVALUATION_PROFILE", str(profile_path))

    settings = Settings.from_environment()

    assert settings.runtime_mode == "evaluation"
    assert settings.evaluation_profile is not None
    assert settings.evaluation_profile.model == "gpt-4o-mini"
