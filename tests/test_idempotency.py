from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app
from tests.test_api_add_search import add_payload


def test_repeated_add_is_successful_without_duplicate_messages(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")
    with TestClient(app) as client:
        first = client.post("/v1/memories/add", json=add_payload())
        repeated = client.post("/v1/memories/add", json=add_payload())

        assert first.status_code == repeated.status_code == 200
        assert first.json() == repeated.json()
        assert app.state.store.count_messages() == 2


def test_request_id_reuse_with_changed_payload_returns_409(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")
    changed = add_payload()
    changed["messages"][0]["content"] = "A conflicting fact."

    with TestClient(app) as client:
        assert client.post("/v1/memories/add", json=add_payload()).status_code == 200
        response = client.post("/v1/memories/add", json=changed)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "request_id already exists with a different payload"
    }
