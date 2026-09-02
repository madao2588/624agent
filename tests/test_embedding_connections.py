from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_memory.app import create_app
from aml_memory.connections import (
    EmbeddingConnectionNotFoundError,
    EmbeddingConnectionRegistry,
)
from aml_memory.models import EmbeddingBatch
from aml_memory.schemas import EmbeddingConnectionCreate


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeEmbedder:
    model = "semantic-test"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        self.calls.append(texts)
        return EmbeddingBatch(
            model=self.model,
            vectors=tuple((1.0, 0.0) for _text in texts),
        )


def test_registry_uses_sliding_expiry_and_deletes_connections() -> None:
    clock = FakeClock()
    wall_time = datetime(2026, 9, 1, tzinfo=UTC)
    registry = EmbeddingConnectionRegistry(
        ttl_seconds=1_800,
        clock=clock,
        utc_now=lambda: wall_time + timedelta(seconds=clock.value - 100.0),
    )
    embedder = FakeEmbedder()

    created = registry.add(
        provider="openai-compatible",
        model=embedder.model,
        base_url="https://embedding.example/v1",
        embedder=embedder,
    )

    assert created.connection_id
    assert created.expires_at == wall_time + timedelta(seconds=1_800)
    clock.advance(1_200)
    resolved = registry.resolve(created.connection_id)
    assert resolved.embedder is embedder
    assert resolved.expires_at == wall_time + timedelta(seconds=3_000)

    clock.advance(1_801)
    with pytest.raises(EmbeddingConnectionNotFoundError):
        registry.resolve(created.connection_id)

    replacement = registry.add(
        provider="openai",
        model=embedder.model,
        base_url="https://api.openai.com/v1",
        embedder=embedder,
    )
    assert registry.delete(replacement.connection_id) is True
    assert registry.delete(replacement.connection_id) is False


def test_create_connection_probes_provider_without_returning_or_persisting_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-test-secret-never-return"
    embedder = FakeEmbedder()
    received: list[EmbeddingConnectionCreate] = []

    def factory(config: EmbeddingConnectionCreate) -> FakeEmbedder:
        received.append(config)
        return embedder

    database_path = tmp_path / "memory.db"
    app = create_app(database_path=database_path, connection_embedder_factory=factory)

    with TestClient(app) as client:
        response = client.post(
            "/v1/embedding-connections",
            json={
                "provider": "openai-compatible",
                "api_key": secret,
                "model": "semantic-test",
                "base_url": "https://embedding.example/v1",
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "connection_id",
        "provider",
        "model",
        "base_url",
        "expires_at",
    }
    assert secret not in response.text
    assert secret not in caplog.text
    assert secret.encode() not in database_path.read_bytes()
    assert received[0].api_key.get_secret_value() == secret
    assert embedder.calls == [["AML Memory connection test"]]


def test_connection_header_enables_semantic_add_and_search_then_can_be_revoked(
    tmp_path: Path,
) -> None:
    embedder = FakeEmbedder()
    app = create_app(
        database_path=tmp_path / "memory.db",
        neighbor_radius=0,
        connection_embedder_factory=lambda _config: embedder,
    )

    with TestClient(app) as client:
        connected = client.post(
            "/v1/embedding-connections",
            json={
                "provider": "openai",
                "api_key": "sk-test",
                "model": "semantic-test",
            },
        )
        connection_id = connected.json()["connection_id"]
        headers = {"X-Embedding-Connection": connection_id}
        added = client.post(
            "/v1/memories/add",
            headers=headers,
            json={
                "request_id": "semantic-session-add",
                "user_id": "semantic-user",
                "session_id": "semantic-session",
                "messages": [
                    {
                        "role": "user",
                        "content": "Weekends are reserved for cycling beyond the city limits.",
                    }
                ],
            },
        )
        searched = client.post(
            "/v1/memories/search",
            headers=headers,
            json={
                "query": "Which outdoor hobby is enjoyed during spare time?",
                "user_id": "semantic-user",
                "top_k": 3,
            },
        )
        status = client.get(f"/v1/embedding-connections/{connection_id}")
        removed = client.delete(f"/v1/embedding-connections/{connection_id}")
        rejected = client.post(
            "/v1/memories/search",
            headers=headers,
            json={"query": "hobby", "user_id": "semantic-user", "top_k": 3},
        )

    assert connected.status_code == 201
    assert added.status_code == 200
    assert searched.status_code == 200
    assert "cycling" in searched.json()["data"][0]["content"]
    assert status.status_code == 200
    assert removed.status_code == 200
    assert removed.json() == {"success": True}
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "embedding connection is invalid or expired"}


def test_connections_with_the_same_model_name_keep_vector_spaces_separate(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_path=tmp_path / "memory.db",
        neighbor_radius=0,
        connection_embedder_factory=lambda _config: FakeEmbedder(),
    )

    with TestClient(app) as client:
        first_connection = client.post(
            "/v1/embedding-connections",
            json={
                "provider": "openai-compatible",
                "api_key": "first-key",
                "model": "shared-model-name",
                "base_url": "https://first.example/v1",
            },
        ).json()["connection_id"]
        second_connection = client.post(
            "/v1/embedding-connections",
            json={
                "provider": "openai-compatible",
                "api_key": "second-key",
                "model": "shared-model-name",
                "base_url": "https://second.example/v1",
            },
        ).json()["connection_id"]
        client.post(
            "/v1/memories/add",
            headers={"X-Embedding-Connection": first_connection},
            json={
                "request_id": "first-space-memory",
                "user_id": "shared-user",
                "session_id": "first-space",
                "messages": [{"role": "user", "content": "First provider memory."}],
            },
        )
        client.post(
            "/v1/memories/add",
            headers={"X-Embedding-Connection": second_connection},
            json={
                "request_id": "second-space-memory",
                "user_id": "shared-user",
                "session_id": "second-space",
                "messages": [{"role": "user", "content": "Second provider memory."}],
            },
        )
        searched = client.post(
            "/v1/memories/search",
            headers={"X-Embedding-Connection": first_connection},
            json={
                "query": "semantic query without source words",
                "user_id": "shared-user",
                "top_k": 10,
            },
        )

    contents = [item["content"] for item in searched.json()["data"]]
    assert any("First provider memory." in content for content in contents)
    assert all("Second provider memory." not in content for content in contents)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "provider": "openai-compatible",
            "api_key": "secret",
            "model": "model",
        },
        {
            "provider": "openai-compatible",
            "api_key": "secret",
            "model": "model",
            "base_url": "ftp://embedding.example/v1",
        },
        {
            "provider": "openai-compatible",
            "api_key": "secret",
            "model": "model",
            "base_url": "https://user:password@embedding.example/v1",
        },
        {
            "provider": "openai-compatible",
            "api_key": "secret",
            "model": "model",
            "base_url": "https://embedding.example/v1?api_key=secret",
        },
    ],
)
def test_connection_rejects_missing_or_unsafe_custom_base_urls(
    tmp_path: Path,
    payload: dict[str, str],
) -> None:
    app = create_app(
        database_path=tmp_path / "memory.db",
        connection_embedder_factory=lambda _config: FakeEmbedder(),
    )

    with TestClient(app) as client:
        response = client.post("/v1/embedding-connections", json=payload)

    assert response.status_code == 422
