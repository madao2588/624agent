from fastapi.testclient import TestClient


def _add(
    client: TestClient,
    *,
    request_id: str,
    user_id: str,
    content: str,
) -> None:
    response = client.post(
        "/v1/memories/add",
        json={
            "request_id": request_id,
            "user_id": user_id,
            "session_id": request_id,
            "messages": [{"role": "user", "content": content}],
        },
    )
    assert response.status_code == 200


def test_diagnostics_explains_recall_without_changing_official_search_contract(
    client: TestClient,
) -> None:
    user_id = "diagnostics-user"
    _add(
        client,
        request_id="atlas-old",
        user_id=user_id,
        content="The Atlas meeting is on 2026-09-03 at Juniper Cafe.",
    )
    _add(
        client,
        request_id="atlas-cancelled",
        user_id=user_id,
        content="The Atlas meeting at Juniper Cafe is cancelled.",
    )
    _add(
        client,
        request_id="atlas-resumed",
        user_id=user_id,
        content="The Atlas meeting resumed on 2026-09-05 at Juniper Cafe.",
    )

    payload = {
        "query": "Show the Atlas meeting history at Juniper Cafe",
        "user_id": user_id,
        "top_k": 10,
    }
    official = client.post("/v1/memories/search", json=payload)
    diagnostics = client.post("/v1/memories/search/diagnostics", json=payload)

    assert official.status_code == 200
    assert official.json()["data"]
    assert set(official.json()["data"][0]) == {
        "id",
        "content",
        "score",
        "created_at",
    }

    assert diagnostics.status_code == 200
    body = diagnostics.json()
    assert set(body) == {"data", "relations"}
    assert len(body["data"]) >= 3
    assert all(item["reasons"] for item in body["data"])
    assert any(item["facets"] for item in body["data"])
    assert {item["state"] for item in body["data"]} >= {"active", "history"}

    evidence_ids = {item["id"] for item in body["data"]}
    assert body["relations"]
    assert any(edge["relation"] == "supersedes" for edge in body["relations"])
    assert all(edge["source_id"] in evidence_ids for edge in body["relations"])
    assert all(edge["target_id"] in evidence_ids for edge in body["relations"])


def test_diagnostics_preserves_user_isolation(client: TestClient) -> None:
    _add(
        client,
        request_id="private-one",
        user_id="user-one",
        content="Project Lantern uses the private color vermilion.",
    )
    _add(
        client,
        request_id="private-two",
        user_id="user-two",
        content="Project Lantern uses the private color cobalt.",
    )

    response = client.post(
        "/v1/memories/search/diagnostics",
        json={"query": "Project Lantern color", "user_id": "user-one", "top_k": 10},
    )

    assert response.status_code == 200
    serialized = response.text
    assert "vermilion" in serialized
    assert "cobalt" not in serialized


def test_diagnostics_bounds_dense_relation_output(client: TestClient) -> None:
    for index in range(40):
        _add(
            client,
            request_id=f"dense-{index}",
            user_id="dense-user",
            content=f"Omar recorded project note number {index}.",
        )

    response = client.post(
        "/v1/memories/search/diagnostics",
        json={"query": "Omar project note", "user_id": "dense-user", "top_k": 100},
    )

    assert response.status_code == 200
    assert len(response.json()["relations"]) <= 500
