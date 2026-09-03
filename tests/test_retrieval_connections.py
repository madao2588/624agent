from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app
from aml_memory.schemas import RetrievalConnectionCreate


class FakeQueryExpander:
    def __init__(self, terms: list[str] | None = None) -> None:
        self.calls: list[str] = []
        self.terms = terms or ["cycling", "bike rides"]

    def expand(self, query: str) -> list[str]:
        self.calls.append(query)
        return self.terms


def test_deepseek_connection_expands_search_but_keeps_add_local(
    tmp_path: Path,
) -> None:
    expander = FakeQueryExpander()
    received: list[RetrievalConnectionCreate] = []

    def factory(config: RetrievalConnectionCreate) -> FakeQueryExpander:
        received.append(config)
        return expander

    database_path = tmp_path / "memory.db"
    app = create_app(
        database_path=database_path,
        neighbor_radius=0,
        connection_query_expander_factory=factory,
    )

    with TestClient(app) as client:
        connected = client.post(
            "/v1/retrieval-connections",
            json={
                "provider": "deepseek",
                "api_key": "deepseek-test-secret",
            },
        )
        connection_id = connected.json()["connection_id"]
        headers = {"X-Retrieval-Connection": connection_id}
        probe_calls = list(expander.calls)
        added = client.post(
            "/v1/memories/add",
            headers=headers,
            json={
                "request_id": "deepseek-local-add",
                "user_id": "deepseek-user",
                "session_id": "deepseek-session",
                "messages": [
                    {
                        "role": "user",
                        "content": "Weekends are reserved for cycling outside the city.",
                    }
                ],
            },
        )
        calls_after_add = list(expander.calls)
        searched = client.post(
            "/v1/memories/search",
            headers=headers,
            json={
                "query": "Which outdoor hobby do I enjoy?",
                "user_id": "deepseek-user",
                "top_k": 3,
            },
        )
        status = client.get(f"/v1/retrieval-connections/{connection_id}")
        removed = client.delete(f"/v1/retrieval-connections/{connection_id}")

    assert connected.status_code == 201
    assert connected.json()["capability"] == "query-expansion"
    assert connected.json()["model"] == "deepseek-v4-flash"
    assert connected.json()["base_url"] == "https://api.deepseek.com"
    assert "deepseek-test-secret" not in connected.text
    assert received[0].api_key.get_secret_value() == "deepseek-test-secret"
    assert probe_calls == ["Find memories about a changed meeting plan."]
    assert added.status_code == 200
    assert calls_after_add == probe_calls
    assert searched.status_code == 200
    assert expander.calls[-1] == "Which outdoor hobby do I enjoy?"
    assert "cycling" in searched.json()["data"][0]["content"]
    assert status.status_code == 200
    assert status.json()["capability"] == "query-expansion"
    assert removed.json() == {"success": True}
    assert b"deepseek-test-secret" not in database_path.read_bytes()


def test_deepseek_connection_supplements_a_partial_local_match(tmp_path: Path) -> None:
    expander = FakeQueryExpander(["brake pads", "replace"])
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
        headers = {"X-Retrieval-Connection": connected.json()["connection_id"]}
        client.post(
            "/v1/memories/add",
            headers=headers,
            json={
                "request_id": "deepseek-partial-add",
                "user_id": "deepseek-user",
                "session_id": "maintenance-session",
                "messages": [
                    {
                        "role": "user",
                        "content": "My bicycle needs maintenance before spring.",
                    },
                    {
                        "role": "assistant",
                        "content": "Replace the worn brake pads next week.",
                    },
                ],
            },
        )
        searched = client.post(
            "/v1/memories/search",
            headers=headers,
            json={
                "query": "What bicycle maintenance is pending?",
                "user_id": "deepseek-user",
                "top_k": 3,
            },
        )
        diagnostics = client.post(
            "/v1/memories/search/diagnostics",
            headers=headers,
            json={
                "query": "What bicycle maintenance is pending?",
                "user_id": "deepseek-user",
                "top_k": 3,
            },
        )

    contents = [item["content"] for item in searched.json()["data"]]
    assert searched.status_code == 200
    assert any("bicycle needs maintenance" in content for content in contents)
    assert any("Replace the worn brake pads" in content for content in contents)
    detail = next(
        item
        for item in diagnostics.json()["data"]
        if "Replace the worn brake pads" in item["content"]
    )
    assert "model-expanded" in detail["reasons"]


def test_old_embedding_routes_and_header_remain_available(tmp_path: Path) -> None:
    from tests.test_embedding_connections import FakeEmbedder

    app = create_app(
        database_path=tmp_path / "memory.db",
        connection_embedder_factory=lambda _config: FakeEmbedder(),
    )

    with TestClient(app) as client:
        connected = client.post(
            "/v1/embedding-connections",
            json={
                "provider": "openai",
                "api_key": "test-secret",
                "model": "semantic-test",
            },
        )
        connection_id = connected.json()["connection_id"]
        status = client.get(f"/v1/embedding-connections/{connection_id}")
        searched = client.post(
            "/v1/memories/search",
            headers={"X-Embedding-Connection": connection_id},
            json={"query": "anything", "user_id": "user", "top_k": 3},
        )

    assert connected.status_code == 201
    assert "capability" not in connected.json()
    assert status.status_code == 200
    assert searched.status_code == 200


def test_conflicting_connection_headers_are_rejected(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")

    with TestClient(app) as client:
        response = client.post(
            "/v1/memories/search",
            headers={
                "X-Retrieval-Connection": "new-id",
                "X-Embedding-Connection": "old-id",
            },
            json={"query": "hobby", "user_id": "user", "top_k": 3},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "connection headers disagree"}
