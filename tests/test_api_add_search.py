from fastapi.testclient import TestClient


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
