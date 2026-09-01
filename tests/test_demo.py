from pathlib import Path

from fastapi.testclient import TestClient

from aml_memory.app import create_app


def test_demo_page_is_public_accessible_and_not_cached(tmp_path: Path) -> None:
    app = create_app(
        database_path=tmp_path / "memory.db",
        auth_scheme="bearer",
        api_key="demo-test-secret",
    )

    with TestClient(app) as client:
        response = client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"

    page = response.text
    assert '<main id="main-content"' in page
    assert 'id="load-story"' in page
    assert 'id="identity-primary"' in page
    assert 'id="identity-comparison"' in page
    assert 'id="custom-memory"' in page
    assert 'id="memory-query"' in page
    assert 'id="search-results"' in page
    assert 'id="start-fresh"' in page
    assert 'id="status-message"' in page
    assert 'aria-live="polite"' in page


def test_demo_page_does_not_expand_the_evaluation_api_contract(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/demo" not in paths
