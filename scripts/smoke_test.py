"""Exercise the public HTTP contract without third-party client dependencies."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

    status, health = request_json(base_url, "/health")
    require(status == 200 and health == {"status": "ok"}, "health check failed")

    for suffix, private_value in (("a", "SMOKE_ALPHA_41"), ("b", "SMOKE_BETA_92")):
        status, response = request_json(
            base_url,
            "/v1/memories/add",
            method="POST",
            payload={
                "request_id": f"smoke-request-{suffix}",
                "user_id": f"smoke-user-{suffix}",
                "session_id": f"smoke-session-{suffix}",
                "messages": [
                    {
                        "role": "user",
                        "timestamp": 1_704_067_200_000,
                        "content": f"The shared recovery codename is {private_value}.",
                    }
                ],
            },
        )
        require(status == 200 and response.get("success") is True, f"Add failed for {suffix}")

    status, response = request_json(
        base_url,
        "/v1/memories/search",
        method="POST",
        payload={
            "query": "shared recovery codename",
            "user_id": "smoke-user-a",
            "top_k": 100,
        },
    )
    require(status == 200 and list(response) == ["data"], "Search contract failed")
    contents = [str(item["content"]) for item in response["data"]]
    require(any("SMOKE_ALPHA_41" in content for content in contents), "own memory missing")
    require(all("SMOKE_BETA_92" not in content for content in contents), "user isolation failed")

    print("Smoke test passed: health, Add, Search, SQLite storage, and user isolation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
