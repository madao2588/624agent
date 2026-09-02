# ruff: noqa: RUF001 - natural Chinese test questions keep native punctuation

import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from aml_memory.enrichment import OpenAIEvaluationProvider
from aml_memory.errors import EvaluationServiceError


class StubHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "StubHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _response(output: dict) -> dict:
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(output),
                    }
                ],
            },
        ],
    }


def test_evaluation_add_uses_responses_structured_output_and_parses_facets() -> None:
    captured: dict[str, object] = {}

    def opener(request: Request, timeout: float) -> StubHttpResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["body"] = json.loads(bytes(request.data or b"{}").decode("utf-8"))
        return StubHttpResponse(
            _response(
                {
                    "messages": [
                        {
                            "index": 0,
                            "facets": [
                                {
                                    "kind": "entity",
                                    "value": "Nimbus",
                                    "confidence": 0.93,
                                },
                                {
                                    "kind": "event",
                                    "value": "Atlas review",
                                    "confidence": 0.88,
                                },
                            ],
                        },
                        {"index": 1, "facets": []},
                    ]
                }
            )
        )

    provider = OpenAIEvaluationProvider(
        api_key="evaluation-test-secret",
        model="gpt-4o-mini",
        timeout_seconds=8.0,
        opener=opener,
    )

    facets = provider.enrich(["Nimbus leads the Atlas review.", "Noted."])

    assert facets[0][0].kind == "entity"
    assert facets[0][0].value == "Nimbus"
    assert facets[0][0].normalized_value == "nimbus"
    assert facets[1] == ()
    assert captured == {
        "url": "https://api.openai.com/v1/responses",
        "authorization": "Bearer evaluation-test-secret",
        "timeout": 8.0,
        "body": captured["body"],
    }
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o-mini"
    assert body["store"] is False
    assert body["temperature"] == 0
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert "untrusted source data" in body["instructions"]
    assert json.loads(body["input"])["messages"] == [
        {"index": 0, "content": "Nimbus leads the Atlas review."},
        {"index": 1, "content": "Noted."},
    ]


def test_evaluation_search_always_returns_bounded_deduplicated_terms() -> None:
    captured: dict[str, object] = {}

    def opener(request: Request, _timeout: float) -> StubHttpResponse:
        captured["body"] = json.loads(bytes(request.data or b"{}").decode("utf-8"))
        return StubHttpResponse(
            _response(
                {
                    "search_terms": [
                        "Atlas meeting",
                        "阿特拉斯会议",
                        "atlas meeting",
                        "  ",
                    ]
                }
            )
        )

    provider = OpenAIEvaluationProvider(
        api_key="evaluation-test-secret",
        opener=opener,
    )

    terms = provider.expand("阿特拉斯会议现在是什么状态？")

    assert terms == ["Atlas meeting", "阿特拉斯会议"]
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["text"]["format"]["name"] == "memory_search_plan"
    assert body["max_output_tokens"] == 256
    assert body["input"] == "阿特拉斯会议现在是什么状态？"
    assert "never answer the question" in body["instructions"]


def test_evaluation_provider_rejects_invalid_or_incomplete_output() -> None:
    def opener(_request: Request, _timeout: float) -> StubHttpResponse:
        return StubHttpResponse(
            {
                "status": "incomplete",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "not json"}],
                    }
                ],
            }
        )

    provider = OpenAIEvaluationProvider(
        api_key="evaluation-test-secret",
        opener=opener,
    )

    with pytest.raises(EvaluationServiceError, match="invalid structured output"):
        provider.expand("private question")


def test_evaluation_provider_sanitizes_http_failures() -> None:
    secret = "evaluation-private-secret"
    private_text = "private message body"

    def opener(request: Request, _timeout: float) -> StubHttpResponse:
        raise HTTPError(request.full_url, 429, "body echoed", {}, None)

    provider = OpenAIEvaluationProvider(api_key=secret, opener=opener)

    with pytest.raises(EvaluationServiceError) as error:
        provider.enrich([private_text])

    assert str(error.value) == "evaluation service returned HTTP 429"
    assert secret not in str(error.value)
    assert private_text not in str(error.value)


def test_evaluation_provider_retries_one_transient_failure() -> None:
    calls = 0

    def opener(request: Request, _timeout: float) -> StubHttpResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        return StubHttpResponse(_response({"search_terms": ["Nimbus"]}))

    provider = OpenAIEvaluationProvider(
        api_key="evaluation-test-secret",
        max_attempts=2,
        opener=opener,
    )

    assert provider.expand("meeting") == ["Nimbus"]
    assert calls == 2


def test_evaluation_provider_opens_circuit_after_repeated_failures() -> None:
    calls = 0

    def opener(request: Request, _timeout: float) -> StubHttpResponse:
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 503, "unavailable", {}, None)

    provider = OpenAIEvaluationProvider(
        api_key="evaluation-test-secret",
        max_attempts=1,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=30.0,
        opener=opener,
    )

    with pytest.raises(EvaluationServiceError, match="HTTP 503"):
        provider.expand("first")
    with pytest.raises(EvaluationServiceError, match="HTTP 503"):
        provider.expand("second")
    with pytest.raises(EvaluationServiceError, match="temporarily unavailable"):
        provider.expand("third")

    assert calls == 2
