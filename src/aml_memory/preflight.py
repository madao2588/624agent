"""Black-box compatibility checks for the leaderboard Add/Search contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class PreflightError(RuntimeError):
    """A public API response violated the evaluation contract."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: object


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    operations: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class PreflightConfig:
    base_url: str
    health_path: str = "/health"
    add_path: str = "/v1/memories/add"
    search_path: str = "/v1/memories/search"
    timeout: float = 10.0
    auth_scheme: str = "none"
    api_key: str | None = None
    add_concurrency: int = 64
    search_concurrency: int = 256

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url must not contain embedded credentials")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.add_concurrency <= 0 or self.search_concurrency <= 0:
            raise ValueError("concurrency values must be positive")
        for path in (self.health_path, self.add_path, self.search_path):
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError("endpoint paths must start with one slash")
        normalized_scheme = self.auth_scheme.strip().lower()
        build_auth_headers(normalized_scheme, self.api_key)
        object.__setattr__(self, "auth_scheme", normalized_scheme)
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))


def build_auth_headers(scheme: str, api_key: str | None) -> Mapping[str, str]:
    """Create request headers without accepting a credential on the command line."""

    normalized = scheme.strip().lower()
    if normalized not in {"none", "token", "bearer", "x-api-key"}:
        raise ValueError("auth scheme must be none, token, bearer, or x-api-key")
    has_key = api_key is not None and bool(api_key.strip())
    if normalized == "none":
        if has_key:
            raise ValueError("an API key requires an enabled auth scheme")
        return {}
    if not has_key or api_key is None:
        raise ValueError("an API key is required for the selected auth scheme")
    if normalized == "x-api-key":
        return {"X-Api-Key": api_key}
    return {"Authorization": f"{normalized.title()} {api_key}"}


def validate_add_response(
    response: HttpResponse, *, expected: Mapping[str, str]
) -> None:
    if response.status_code != 200:
        raise PreflightError(f"Add returned HTTP {response.status_code}; expected 200")
    if not isinstance(response.body, dict):
        raise PreflightError("Add response must be a JSON object")
    if response.body.get("success") is not True:
        raise PreflightError("Add response must contain success=true")
    for field in ("request_id", "user_id", "session_id"):
        if response.body.get(field) != expected[field]:
            raise PreflightError(f"Add response did not echo {field} exactly")


def validate_search_response(
    response: HttpResponse, *, top_k: int
) -> list[dict[str, Any]]:
    if response.status_code != 200:
        raise PreflightError(f"Search returned HTTP {response.status_code}; expected 200")
    if not isinstance(response.body, dict):
        raise PreflightError("Search response must be a JSON object")
    data = response.body.get("data")
    if not isinstance(data, list):
        raise PreflightError("Search response must contain a data array")
    if len(data) > top_k:
        raise PreflightError("Search returned more records than top_k")
    validated: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise PreflightError("Each Search record must be a JSON object")
        memory_id = item.get("id")
        content = item.get("content")
        if not isinstance(memory_id, str) or not memory_id.strip():
            raise PreflightError("Each Search record must contain a non-empty id")
        if not isinstance(content, str) or not content.strip():
            raise PreflightError("Each Search record must contain non-empty content")
        score = item.get("score")
        if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool)):
            raise PreflightError("Search score must be numeric when present")
        created_at = item.get("created_at")
        if created_at is not None and not isinstance(created_at, str):
            raise PreflightError("Search created_at must be a string when present")
        validated.append(item)
    return validated


class JsonHttpClient:
    def __init__(self, config: PreflightConfig) -> None:
        self._config = config
        self._auth_headers = build_auth_headers(config.auth_scheme, config.api_key)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> HttpResponse:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers.update(self._auth_headers)
        request = urllib.request.Request(
            f"{self._config.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=_decode_json(response.read()),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status_code=error.code,
                body=_decode_json(error.read()),
            )
        except (TimeoutError, urllib.error.URLError) as error:
            raise PreflightError("HTTP request failed before receiving a response") from error


def _decode_json(payload: bytes) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _timed_check(name: str, operations: int, action: Callable[[], None]) -> CheckResult:
    started = time.perf_counter()
    action()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return CheckResult(name=name, operations=operations, elapsed_ms=elapsed_ms)


def run_preflight(
    config: PreflightConfig,
    *,
    emit: Callable[[CheckResult], None] | None = None,
) -> list[CheckResult]:
    """Exercise the official contract against a running candidate service."""

    client = JsonHttpClient(config)
    run_id = uuid.uuid4().hex[:12]
    primary_marker = f"PREFLIGHTPRIMARY{run_id}"
    foreign_marker = f"PREFLIGHTFOREIGN{run_id}"
    primary_ids = {
        "request_id": f"preflight:{run_id}:primary",
        "user_id": f"preflight:{run_id}:user-primary",
        "session_id": f"preflight:{run_id}:session-primary",
    }
    foreign_ids = {
        "request_id": f"preflight:{run_id}:foreign",
        "user_id": f"preflight:{run_id}:user-foreign",
        "session_id": f"preflight:{run_id}:session-foreign",
    }
    primary_payload: dict[str, Any] = {
        **primary_ids,
        "messages": [
            {
                "role": "user",
                "timestamp": 1_704_067_200_000,
                "content": f"Evaluation marker {primary_marker} belongs to the primary user.",
            }
        ],
    }
    foreign_payload: dict[str, Any] = {
        **foreign_ids,
        "messages": [
            {
                "role": "user",
                "content": f"Private marker {foreign_marker} belongs to another user.",
            }
        ],
    }
    results: list[CheckResult] = []

    def record(result: CheckResult) -> None:
        results.append(result)
        if emit is not None:
            emit(result)

    def health() -> None:
        response = client.request("GET", config.health_path, authenticated=False)
        if not 200 <= response.status_code < 300:
            raise PreflightError(
                f"Health returned HTTP {response.status_code}; expected a 2xx status"
            )

    record(_timed_check("health", 1, health))

    def add_and_retry() -> None:
        for payload, expected in (
            (primary_payload, primary_ids),
            (primary_payload, primary_ids),
            (foreign_payload, foreign_ids),
        ):
            response = client.request("POST", config.add_path, payload=payload)
            validate_add_response(response, expected=expected)

    record(_timed_check("add-sync-idempotency", 3, add_and_retry))

    primary_query = {
        "query": "Identify the evaluation selection",
        "options": [primary_marker, "UNRELATEDOPTION"],
        "user_id": primary_ids["user_id"],
        "top_k": 100,
    }

    def search_and_isolate() -> None:
        first = validate_search_response(
            client.request("POST", config.search_path, payload=primary_query),
            top_k=100,
        )
        second = validate_search_response(
            client.request("POST", config.search_path, payload=primary_query),
            top_k=100,
        )
        if not any(primary_marker in item["content"] for item in first):
            raise PreflightError("Search could not retrieve memory using question options")
        if [item["id"] for item in first] != [item["id"] for item in second]:
            raise PreflightError("Repeated Search did not preserve stable result ordering")
        isolation_query = {
            "query": foreign_marker,
            "user_id": primary_ids["user_id"],
            "top_k": 1,
        }
        isolated = validate_search_response(
            client.request("POST", config.search_path, payload=isolation_query),
            top_k=1,
        )
        if any(foreign_marker in item["content"] for item in isolated):
            raise PreflightError("Search leaked memory across user_id boundaries")

    record(_timed_check("search-options-order-isolation", 3, search_and_isolate))

    parallel_payloads: list[dict[str, Any]] = []
    for index in range(config.add_concurrency):
        marker = f"PREFLIGHTPARALLEL{run_id}X{index}"
        parallel_payloads.append(
            {
                "request_id": f"preflight:{run_id}:parallel:{index}",
                "user_id": primary_ids["user_id"],
                "session_id": f"preflight:{run_id}:parallel-session:{index}",
                "messages": [{"role": "user", "content": f"Parallel marker {marker}."}],
            }
        )

    def add_one(payload: dict[str, Any]) -> None:
        expected = {
            field: str(payload[field])
            for field in ("request_id", "user_id", "session_id")
        }
        validate_add_response(
            client.request("POST", config.add_path, payload=payload),
            expected=expected,
        )

    def concurrent_add() -> None:
        with ThreadPoolExecutor(max_workers=config.add_concurrency) as executor:
            list(executor.map(add_one, parallel_payloads))

    record(
        _timed_check(
            "concurrent-add",
            config.add_concurrency,
            concurrent_add,
        )
    )

    def enforce_top_k() -> None:
        data = validate_search_response(
            client.request(
                "POST",
                config.search_path,
                payload={
                    "query": "Parallel marker",
                    "user_id": primary_ids["user_id"],
                    "top_k": 1,
                },
            ),
            top_k=1,
        )
        if len(data) != 1:
            raise PreflightError("Search did not return the expected Top K result")

    record(_timed_check("top-k", 1, enforce_top_k))

    def search_one(index: int) -> None:
        payload = parallel_payloads[index % len(parallel_payloads)]
        marker = str(payload["messages"][0]["content"]).removeprefix(
            "Parallel marker "
        ).removesuffix(".")
        response = client.request(
            "POST",
            config.search_path,
            payload={
                "query": marker,
                "user_id": primary_ids["user_id"],
                "top_k": 5,
            },
        )
        data = validate_search_response(response, top_k=5)
        if not any(marker in item["content"] for item in data):
            raise PreflightError("Concurrent Search did not retrieve its expected marker")

    def concurrent_search() -> None:
        with ThreadPoolExecutor(max_workers=config.search_concurrency) as executor:
            list(executor.map(search_one, range(config.search_concurrency)))

    record(
        _timed_check(
            "concurrent-search",
            config.search_concurrency,
            concurrent_search,
        )
    )
    return results


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a running memory service against the AML Add/Search contract."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--add-path", default="/v1/memories/add")
    parser.add_argument("--search-path", default="/v1/memories/search")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--auth-scheme",
        choices=("none", "token", "bearer", "x-api-key"),
        default="none",
    )
    parser.add_argument(
        "--api-key-env",
        default="MEMORY_API_KEY",
        help="Environment variable containing the API key; key values are never CLI arguments.",
    )
    parser.add_argument("--add-concurrency", type=int, default=64)
    parser.add_argument("--search-concurrency", type=int, default=256)
    return parser


def parse_cli_config(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> PreflightConfig:
    arguments = _argument_parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    api_key = (
        None
        if arguments.auth_scheme == "none"
        else environment.get(arguments.api_key_env)
    )
    return PreflightConfig(
        base_url=arguments.base_url,
        health_path=arguments.health_path,
        add_path=arguments.add_path,
        search_path=arguments.search_path,
        timeout=arguments.timeout,
        auth_scheme=arguments.auth_scheme,
        api_key=api_key,
        add_concurrency=arguments.add_concurrency,
        search_concurrency=arguments.search_concurrency,
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = parse_cli_config(argv)

        def emit(result: CheckResult) -> None:
            print(
                f"PASS {result.name}: operations={result.operations} "
                f"elapsed_ms={result.elapsed_ms}"
            )

        results = run_preflight(config, emit=emit)
    except (PreflightError, ValueError) as error:
        print(f"PRECHECK FAILED: {error}", file=sys.stderr)
        return 1
    total_operations = sum(result.operations for result in results)
    print(f"PRECHECK PASSED: checks={len(results)} operations={total_operations}")
    return 0
