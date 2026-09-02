import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app


def test_health_reports_ready_database(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert (tmp_path / "memory.db").exists()


def test_health_fails_when_a_required_retrieval_index_is_missing(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    app = create_app(database_path=database_path)

    with TestClient(app, raise_server_exceptions=False) as client:
        with sqlite3.connect(database_path) as connection:
            connection.execute("DROP INDEX idx_message_facets_user_kind_value")
            connection.commit()
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "memory store not ready"}
