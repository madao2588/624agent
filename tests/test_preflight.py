from collections.abc import Mapping

import pytest

from aml_memory.preflight import (
    HttpResponse,
    PreflightConfig,
    PreflightError,
    build_auth_headers,
    parse_cli_config,
    validate_add_response,
    validate_search_response,
)


@pytest.mark.parametrize(
    ("scheme", "key", "expected"),
    [
        ("none", None, {}),
        ("token", "secret", {"Authorization": "Token secret"}),
        ("bearer", "secret", {"Authorization": "Bearer secret"}),
        ("x-api-key", "secret", {"X-Api-Key": "secret"}),
    ],
)
def test_build_auth_headers_supports_official_schemes(
    scheme: str, key: str | None, expected: Mapping[str, str]
) -> None:
    assert build_auth_headers(scheme, key) == expected


@pytest.mark.parametrize(
    ("scheme", "key"),
    [("invalid", "secret"), ("token", None), ("bearer", ""), ("x-api-key", " ")],
)
def test_build_auth_headers_rejects_invalid_configuration(
    scheme: str, key: str | None
) -> None:
    with pytest.raises(ValueError):
        build_auth_headers(scheme, key)


def test_validate_add_response_requires_exact_success_echo() -> None:
    expected = {
        "request_id": "request-1",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    response = HttpResponse(
        status_code=200,
        body={"success": True, **expected},
    )

    validate_add_response(response, expected=expected)

    for broken in (
        HttpResponse(status_code=202, body=response.body),
        HttpResponse(status_code=200, body={"success": False, **expected}),
        HttpResponse(status_code=200, body={"success": True, **expected, "user_id": "other"}),
    ):
        with pytest.raises(PreflightError):
            validate_add_response(broken, expected=expected)


def test_validate_search_response_enforces_shape_and_top_k() -> None:
    valid = HttpResponse(
        status_code=200,
        body={
            "data": [
                {"id": "mem-1", "content": "first", "score": 0.9},
                {"id": "mem-2", "content": "second"},
            ]
        },
    )

    assert validate_search_response(valid, top_k=2) == valid.body["data"]

    broken_responses = (
        HttpResponse(status_code=500, body={"data": []}),
        HttpResponse(status_code=200, body=[]),
        HttpResponse(status_code=200, body={"items": []}),
        HttpResponse(status_code=200, body={"data": [{"id": "", "content": "x"}]}),
        HttpResponse(status_code=200, body={"data": [{"id": "1", "content": ""}]}),
        HttpResponse(
            status_code=200,
            body={
                "data": [
                    {"id": "1", "content": "a"},
                    {"id": "2", "content": "b"},
                ]
            },
        ),
    )
    for broken in broken_responses:
        with pytest.raises(PreflightError):
            validate_search_response(broken, top_k=1)


def test_contract_errors_never_include_server_body_or_secret() -> None:
    secret = "do-not-print-this-key"
    response = HttpResponse(status_code=401, body={"detail": secret})

    with pytest.raises(PreflightError) as captured:
        validate_add_response(
            response,
            expected={"request_id": "r", "user_id": "u", "session_id": "s"},
        )

    assert secret not in str(captured.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "ftp://example.com"},
        {"base_url": "https://user:password@example.com"},
        {"base_url": "http://example.com", "timeout": 0},
        {"base_url": "http://example.com", "add_concurrency": 0},
        {"base_url": "http://example.com", "search_concurrency": 0},
    ],
)
def test_preflight_configuration_rejects_unsafe_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PreflightConfig(**overrides)  # type: ignore[arg-type]


def test_cli_reads_api_key_only_from_named_environment_variable() -> None:
    config = parse_cli_config(
        [
            "--base-url",
            "https://memory.example.test",
            "--auth-scheme",
            "bearer",
            "--api-key-env",
            "TEST_MEMORY_KEY",
            "--add-concurrency",
            "4",
            "--search-concurrency",
            "8",
        ],
        environ={"TEST_MEMORY_KEY": "environment-secret"},
    )

    assert config.api_key == "environment-secret"
    assert config.auth_scheme == "bearer"
    assert config.add_concurrency == 4
    assert config.search_concurrency == 8


def test_preflight_defaults_match_the_maximum_evaluation_concurrency() -> None:
    config = parse_cli_config(
        ["--base-url", "http://127.0.0.1:8000"],
        environ={},
    )

    assert config.add_concurrency == 64
    assert config.search_concurrency == 256


def test_cli_rejects_missing_key_without_disclosing_environment() -> None:
    with pytest.raises(ValueError, match="required") as captured:
        parse_cli_config(
            [
                "--base-url",
                "https://memory.example.test",
                "--auth-scheme",
                "token",
                "--api-key-env",
                "ABSENT_KEY",
            ],
            environ={"UNRELATED_SECRET": "do-not-print"},
        )

    assert "do-not-print" not in str(captured.value)
