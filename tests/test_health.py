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
