from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_memory.app import create_app
from aml_memory.config import Settings


def add_payload() -> dict:
    return {
        "request_id": "auth-request",
        "user_id": "auth-user",
        "session_id": "auth-session",
        "messages": [{"role": "user", "content": "authenticated memory"}],
    }


@contextmanager
def authenticated_client(
    tmp_path: Path, *, scheme: str, api_key: str
) -> Iterator[TestClient]:
    app = create_app(
        database_path=tmp_path / f"{scheme}.db",
        auth_scheme=scheme,
        api_key=api_key,
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    ("scheme", "headers"),
    [
        ("token", {"Authorization": "Token evaluation-secret"}),
        ("bearer", {"Authorization": "Bearer evaluation-secret"}),
        ("x-api-key", {"X-Api-Key": "evaluation-secret"}),
    ],
)
def test_supported_auth_schemes_protect_add_and_search(
    tmp_path: Path, scheme: str, headers: dict[str, str]
) -> None:
    with authenticated_client(
        tmp_path, scheme=scheme, api_key="evaluation-secret"
    ) as client:
        missing = client.post("/v1/memories/add", json=add_payload())
        wrong = client.post(
            "/v1/memories/add",
            json=add_payload(),
            headers={
                "Authorization": "Bearer wrong-secret",
                "X-Api-Key": "wrong-secret",
            },
        )
        added = client.post("/v1/memories/add", json=add_payload(), headers=headers)
        searched = client.post(
            "/v1/memories/search",
            json={"query": "authenticated", "user_id": "auth-user", "top_k": 10},
            headers=headers,
        )

    expected_error = {"detail": {"reason": "invalid or missing API credential"}}
    assert missing.status_code == 401
    assert missing.json() == expected_error
    assert wrong.status_code == 401
    assert wrong.json() == expected_error
    assert added.status_code == 200
    assert searched.status_code == 200
    assert searched.json()["data"]


def test_health_remains_public_when_api_auth_is_enabled(tmp_path: Path) -> None:
    with authenticated_client(
        tmp_path, scheme="bearer", api_key="evaluation-secret"
    ) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_failure_does_not_echo_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "never-log-this-evaluation-secret"
    with authenticated_client(tmp_path, scheme="token", api_key=secret) as client:
        response = client.post(
            "/v1/memories/add",
            json=add_payload(),
            headers={"Authorization": f"Token {secret}-wrong"},
        )

    assert response.status_code == 401
    assert secret not in response.text
    assert secret not in caplog.text


@pytest.mark.parametrize(
    ("scheme", "api_key"),
    [
        ("unsupported", "secret"),
        ("token", None),
        ("bearer", ""),
        ("x-api-key", "   "),
    ],
)
def test_invalid_auth_configuration_is_rejected(
    tmp_path: Path, scheme: str, api_key: str | None
) -> None:
    with pytest.raises(ValueError):
        Settings(database_path=tmp_path / "memory.db", auth_scheme=scheme, api_key=api_key)
