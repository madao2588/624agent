import logging

from fastapi.testclient import TestClient


def test_request_payloads_and_queries_are_not_written_to_logs(
    client: TestClient, caplog: object
) -> None:
    secret_memory = "DO_NOT_LOG_MEMORY_7f31"
    secret_query = "DO_NOT_LOG_QUERY_b802"

    with caplog.at_level(logging.INFO, logger="aml_memory"):  # type: ignore[attr-defined]
        client.post(
            "/v1/memories/add",
            json={
                "request_id": "safe-log-request",
                "user_id": "user-1",
                "session_id": "session-1",
                "messages": [{"role": "user", "content": secret_memory}],
            },
        )
        client.post(
            "/v1/memories/search",
            json={"query": secret_query, "user_id": "user-1", "top_k": 100},
        )

    captured = caplog.text  # type: ignore[attr-defined]
    assert secret_memory not in captured
    assert secret_query not in captured
