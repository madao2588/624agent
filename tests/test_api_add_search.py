# ruff: noqa: RUF001 - natural Chinese test questions keep native punctuation

from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app
from aml_memory.errors import EmbeddingServiceError, EvaluationServiceError
from aml_memory.models import EmbeddingBatch, MemoryFacet


class FakeEmbedder:
    model = "semantic-test"

    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        self._vectors = vectors

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            model=self.model,
            vectors=tuple(self._vectors[text] for text in texts),
        )


class FailingEmbedder:
    model = "semantic-test"

    def embed(self, _texts: list[str]) -> EmbeddingBatch:
        raise EmbeddingServiceError("embedding service unavailable")


class ToggleEmbedder:
    model = "semantic-test"

    def __init__(self) -> None:
        self.calls = 0
        self.available = True

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        self.calls += 1
        if not self.available:
            raise EmbeddingServiceError("embedding service unavailable")
        return EmbeddingBatch(
            model=self.model,
            vectors=tuple((1.0, 0.0) for _text in texts),
        )


class EmptyQueryExpander:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def expand(self, query: str) -> list[str]:
        self.calls.append(query)
        return []


class FakeEvaluationProvider:
    def __init__(self) -> None:
        self.enrich_calls: list[list[str]] = []
        self.expand_calls: list[str] = []
        self.available = True

    def enrich(self, contents: list[str]) -> tuple[tuple[MemoryFacet, ...], ...]:
        self.enrich_calls.append(contents)
        if not self.available:
            raise EvaluationServiceError("evaluation service unavailable")
        return tuple(
            (
                MemoryFacet(
                    kind="entity",
                    value="Nimbus",
                    normalized_value="nimbus",
                    confidence=0.95,
                ),
            )
            for _content in contents
        )

    def expand(self, query: str) -> list[str]:
        self.expand_calls.append(query)
        if not self.available:
            raise EvaluationServiceError("evaluation service unavailable")
        return ["Nimbus"]


def _enable_evaluation_mode(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setenv("MEMORY_RUNTIME_MODE", "evaluation")
    monkeypatch.setenv("MEMORY_EVALUATION_API_KEY", "evaluation-test-secret")
    monkeypatch.setenv("MEMORY_EVALUATION_PROFILE", str(profile_path))


def add_payload(*, request_id: str = "request-1", user_id: str = "user-1") -> dict:
    return {
        "request_id": request_id,
        "user_id": user_id,
        "session_id": "session-1",
        "messages": [
            {
                "role": "user",
                "timestamp": 1_704_067_200_000,
                "content": "I adopted a cat named Luna.",
            },
            {"role": "assistant", "content": "Noted."},
        ],
    }


def test_add_is_immediately_searchable_and_returns_evidence_only(client: TestClient) -> None:
    add_response = client.post("/v1/memories/add", json=add_payload())

    assert add_response.status_code == 200
    assert add_response.json() == {
        "success": True,
        "request_id": "request-1",
        "user_id": "user-1",
        "session_id": "session-1",
    }

    search_response = client.post(
        "/v1/memories/search",
        json={"query": "What is my cat named?", "user_id": "user-1", "top_k": 100},
    )

    assert search_response.status_code == 200
    body = search_response.json()
    assert list(body) == ["data"]
    assert body["data"]
    assert "Luna" in body["data"][0]["content"]
    assert all("answer" not in item for item in body["data"])


def test_search_respects_top_k_and_returns_empty_data_for_no_match(client: TestClient) -> None:
    client.post("/v1/memories/add", json=add_payload())

    capped = client.post(
        "/v1/memories/search",
        json={"query": "Luna cat", "user_id": "user-1", "top_k": 1},
    )
    missing = client.post(
        "/v1/memories/search",
        json={"query": "spaceship", "user_id": "user-1", "top_k": 100},
    )

    assert capped.status_code == 200
    assert len(capped.json()["data"]) == 1
    assert missing.status_code == 200
    assert missing.json() == {"data": []}


def test_search_uses_answer_options_as_retrieval_clues(client: TestClient) -> None:
    client.post(
        "/v1/memories/add",
        json={
            "request_id": "request-options",
            "user_id": "user-options",
            "session_id": "session-options",
            "messages": [
                {
                    "role": "user",
                    "content": "The red planet discussed in class was Mars.",
                }
            ],
        },
    )

    response = client.post(
        "/v1/memories/search",
        json={
            "query": "Identify selection",
            "options": ["Venus", "Mars", "Jupiter"],
            "user_id": "user-options",
            "top_k": 10,
        },
    )

    assert response.status_code == 200
    assert any("Mars" in item["content"] for item in response.json()["data"])


def test_compatibility_aliases_and_http_validation(client: TestClient) -> None:
    assert client.post("/add", json=add_payload()).status_code == 200
    assert (
        client.post(
            "/search",
            json={"query": "Luna", "user_id": "user-1", "top_k": 100},
        ).status_code
        == 200
    )
    invalid = client.post(
        "/v1/memories/add",
        json={**add_payload(request_id="invalid"), "messages": []},
    )
    assert invalid.status_code == 422


def test_api_can_retrieve_a_semantic_paraphrase_with_injected_embedder(
    tmp_path: Path,
) -> None:
    memory = "I spend free weekends cycling outside the city."
    query = "Which outdoor activity does the person enjoy in spare time?"
    embedder = FakeEmbedder({memory: (1.0, 0.0), query: (1.0, 0.0)})
    app = create_app(
        database_path=tmp_path / "memory.db",
        neighbor_radius=0,
        embedder=embedder,
    )

    with TestClient(app) as semantic_client:
        added = semantic_client.post(
            "/v1/memories/add",
            json={
                "request_id": "request-semantic-api",
                "user_id": "user-1",
                "session_id": "session-1",
                "messages": [{"role": "user", "content": memory}],
            },
        )
        searched = semantic_client.post(
            "/v1/memories/search",
            json={"query": query, "user_id": "user-1", "top_k": 1},
        )

    assert added.status_code == 200
    assert searched.status_code == 200
    assert memory in searched.json()["data"][0]["content"]


def test_retrieval_connection_recalls_english_name_from_chinese_question(
    tmp_path: Path,
) -> None:
    expander = EmptyQueryExpander()
    app = create_app(
        database_path=tmp_path / "memory.db",
        neighbor_radius=0,
        connection_query_expander_factory=lambda _config: expander,
    )

    with TestClient(app) as client:
        connected = client.post(
            "/v1/retrieval-connections",
            json={"provider": "deepseek", "api_key": "deepseek-test-secret"},
        )
        connection_id = connected.json()["connection_id"]
        headers = {"X-Retrieval-Connection": connection_id}
        added = client.post(
            "/v1/memories/add",
            headers=headers,
            json={
                "request_id": "request-cross-language-name",
                "user_id": "user-1",
                "session_id": "session-1",
                "messages": [{"role": "user", "content": "My name is Peter Park."}],
            },
        )
        searched = client.post(
            "/v1/memories/search",
            headers=headers,
            json={"query": "我的名字是什么？", "user_id": "user-1", "top_k": 3},
        )

    assert connected.status_code == 201
    assert added.status_code == 200
    assert searched.status_code == 200
    assert expander.calls == ["Find memories about a changed meeting plan.", "我的名字是什么？"]
    assert len(searched.json()["data"]) == 1
    assert "My name is Peter Park." in searched.json()["data"][0]["content"]


def test_embedding_failure_returns_503_without_partial_add(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db", embedder=FailingEmbedder())

    with TestClient(app) as failing_client:
        response = failing_client.post(
            "/v1/memories/add",
            json={
                "request_id": "request-failed-vector",
                "user_id": "user-1",
                "session_id": "session-1",
                "messages": [{"role": "user", "content": "private content"}],
            },
        )
        count = app.state.store.count_messages()

    assert response.status_code == 503
    assert response.json() == {"detail": "embedding service unavailable"}
    assert count == 0


def test_idempotency_and_conflicts_are_resolved_before_calling_embedder(
    tmp_path: Path,
) -> None:
    embedder = ToggleEmbedder()
    app = create_app(database_path=tmp_path / "memory.db", embedder=embedder)
    payload = add_payload(request_id="request-idempotent-vector")

    with TestClient(app) as vector_client:
        first = vector_client.post("/v1/memories/add", json=payload)
        embedder.available = False
        repeated = vector_client.post("/v1/memories/add", json=payload)
        conflicting = vector_client.post(
            "/v1/memories/add",
            json={
                **payload,
                "messages": [{"role": "user", "content": "different payload"}],
            },
        )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert conflicting.status_code == 409
    assert embedder.calls == 1


def test_evaluation_mode_calls_model_on_add_and_every_search(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _enable_evaluation_mode(monkeypatch, tmp_path)
    provider = FakeEvaluationProvider()
    app = create_app(
        database_path=tmp_path / "memory.db",
        neighbor_radius=0,
        evaluation_provider=provider,
    )
    payload = {
        "request_id": "request-evaluation",
        "user_id": "user-evaluation",
        "session_id": "session-evaluation",
        "messages": [{"role": "user", "content": "The review moved again."}],
    }

    with TestClient(app) as evaluation_client:
        added = evaluation_client.post("/v1/memories/add", json=payload)
        repeated = evaluation_client.post("/v1/memories/add", json=payload)
        first_search = evaluation_client.post(
            "/v1/memories/search",
            json={"query": "Nimbus", "user_id": "user-evaluation", "top_k": 3},
        )
        second_search = evaluation_client.post(
            "/v1/memories/search",
            json={
                "query": "What changed?",
                "user_id": "user-evaluation",
                "top_k": 3,
            },
        )

    assert added.status_code == 200
    assert repeated.status_code == 200
    assert provider.enrich_calls == [["The review moved again."]]
    assert provider.expand_calls == ["Nimbus", "What changed?"]
    assert first_search.status_code == 200
    assert "The review moved again." in first_search.json()["data"][0]["content"]
    assert second_search.status_code == 200


def test_evaluation_add_failure_returns_503_without_partial_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _enable_evaluation_mode(monkeypatch, tmp_path)
    provider = FakeEvaluationProvider()
    provider.available = False
    app = create_app(
        database_path=tmp_path / "memory.db",
        evaluation_provider=provider,
    )

    with TestClient(app) as evaluation_client:
        response = evaluation_client.post(
            "/v1/memories/add",
            json={
                "request_id": "request-failed-evaluation",
                "user_id": "user-evaluation",
                "session_id": "session-evaluation",
                "messages": [{"role": "user", "content": "private content"}],
            },
        )
        count = app.state.store.count_messages()

    assert response.status_code == 503
    assert response.json() == {"detail": "evaluation service unavailable"}
    assert count == 0


def test_evaluation_mode_rejects_temporary_retrieval_connection_headers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _enable_evaluation_mode(monkeypatch, tmp_path)
    provider = FakeEvaluationProvider()
    app = create_app(
        database_path=tmp_path / "memory.db",
        evaluation_provider=provider,
    )

    with TestClient(app) as evaluation_client:
        response = evaluation_client.post(
            "/v1/memories/search",
            headers={"X-Retrieval-Connection": "demo-override"},
            json={"query": "Nimbus", "user_id": "user-evaluation", "top_k": 3},
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "temporary retrieval connections are disabled in evaluation mode"
    }
    assert provider.expand_calls == []
