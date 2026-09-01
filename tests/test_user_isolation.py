from fastapi.testclient import TestClient


def test_search_never_returns_another_users_messages(client: TestClient) -> None:
    for suffix, secret in (("a", "ALPHA-PRIVATE"), ("b", "BETA-PRIVATE")):
        response = client.post(
            "/v1/memories/add",
            json={
                "request_id": f"request-{suffix}",
                "user_id": f"user-{suffix}",
                "session_id": f"session-{suffix}",
                "messages": [
                    {"role": "user", "content": f"The shared codename is {secret}."}
                ],
            },
        )
        assert response.status_code == 200

    response = client.post(
        "/v1/memories/search",
        json={"query": "shared codename", "user_id": "user-a", "top_k": 100},
    )

    contents = [item["content"] for item in response.json()["data"]]
    assert contents
    assert all("ALPHA-PRIVATE" in content for content in contents)
    assert all("BETA-PRIVATE" not in content for content in contents)
