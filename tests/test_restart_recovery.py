from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app


def test_app_restart_recovers_searchable_memories(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    first_app = create_app(database_path=database_path)
    with TestClient(first_app) as client:
        response = client.post(
            "/v1/memories/add",
            json={
                "request_id": "request-1",
                "user_id": "user-1",
                "session_id": "session-1",
                "messages": [{"role": "user", "content": "My recovery word is cedar."}],
            },
        )
        assert response.status_code == 200

    restarted_app = create_app(database_path=database_path)
    with TestClient(restarted_app) as client:
        response = client.post(
            "/v1/memories/search",
            json={"query": "recovery word", "user_id": "user-1", "top_k": 100},
        )

    assert response.status_code == 200
    assert any("cedar" in item["content"] for item in response.json()["data"])
