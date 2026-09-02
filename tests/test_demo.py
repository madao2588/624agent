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
    assert '<link rel="icon" href="data:image/svg+xml' in page
    assert '<main id="main-content"' in page
    assert 'id="load-conversation"' in page
    assert 'id="conversation-stream"' in page
    assert 'id="conversation-form"' in page
    assert 'id="conversation-input"' in page
    assert 'id="recall-panel"' in page
    assert 'id="suggest-meeting"' in page
    assert 'id="retrieval-settings"' in page
    assert 'id="memory-query"' in page
    assert 'id="search-results"' in page
    assert 'id="memory-inspector"' in page
    assert 'id="memory-timeline"' in page
    assert 'id="memory-graph"' in page
    assert 'id="memory-graph-legend"' in page
    assert 'id="start-fresh"' in page
    assert 'id="status-message"' in page
    assert 'aria-live="polite"' in page
    assert 'id="embedding-provider"' in page
    assert 'id="embedding-api-key"' in page
    assert 'id="embedding-model"' in page
    assert 'id="embedding-base-url"' in page
    assert 'id="connect-embedding"' in page
    assert 'id="disconnect-embedding"' in page
    assert 'id="remember-api-key"' in page
    assert 'id="key-storage-note"' in page
    assert 'value="deepseek"' in page
    assert '/v1/retrieval-connections' in page
    assert '/v1/memories/search/diagnostics' in page
    assert 'X-Retrieval-Connection' in page
    assert '只发送搜索问题' in page
    assert 'DeepSeek 双语查询扩展' in page
    assert '没有找到能支持这个问题的记忆。' in page
    assert 'DeepSeek 双语扩展找回' in page
    assert 'sessionStorage' in page
    assert 'X-Embedding-Connection' in page
    assert 'localStorage' in page
    assert 'aml-memory-retrieval-config' in page
    assert 'deleteSavedRetrievalConfig' in page
    assert '同一个人' in page
    assert '多轮对话' in page
    assert 'prefers-reduced-motion' in page
    assert 'sessionId: "preference"' in page
    assert 'sessionId: "meeting-original"' in page
    assert 'sessionId: "meeting-update"' in page
    assert 'role: "assistant"' in page
    assert 'id="identity-primary"' not in page
    assert 'id="identity-comparison"' not in page
    assert 'switchIdentity' not in page
    assert '小周' not in page


def test_demo_page_does_not_expand_the_evaluation_api_contract(tmp_path: Path) -> None:
    app = create_app(database_path=tmp_path / "memory.db")

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/demo" not in paths
    assert "/v1/memories/search/diagnostics" not in paths
