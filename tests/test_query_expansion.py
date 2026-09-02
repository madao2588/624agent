import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from aml_memory.errors import QueryExpansionServiceError
from aml_memory.query_expansion import DeepSeekQueryExpander


class StubHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "StubHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_deepseek_expander_sends_only_query_and_parses_bounded_terms() -> None:
    captured: dict[str, object] = {}
    private_memory = "PRIVATE STORED MEMORY MUST STAY LOCAL"

    def opener(request: Request, timeout: float) -> StubHttpResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["body"] = json.loads(bytes(request.data or b"{}").decode("utf-8"))
        return StubHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "search_terms": [
                                        "cycling",
                                        "bike rides",
                                        "cycling",
                                        "  ",
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
        )

    expander = DeepSeekQueryExpander(
        api_key="deepseek-test-secret",
        model="deepseek-v4-flash",
        timeout_seconds=8.0,
        opener=opener,
    )

    terms = expander.expand("Which outdoor hobby do I enjoy?")

    assert terms == ["cycling", "bike rides"]
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["authorization"] == "Bearer deepseek-test-secret"
    assert captured["timeout"] == 8.0
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "deepseek-v4-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0
    assert body["stream"] is False
    system_message = body["messages"][0]
    assert system_message["role"] == "system"
    assert "cross-language equivalents" in system_message["content"]
    assert "stored memories" in system_message["content"]
    assert body["messages"][-1] == {
        "role": "user",
        "content": "Which outdoor hobby do I enjoy?",
    }
    serialized = json.dumps(body)
    assert private_memory not in serialized


def test_deepseek_expander_sanitizes_http_failures() -> None:
    query = "private search question"
    secret = "deepseek-secret"

    def opener(request: Request, _timeout: float) -> StubHttpResponse:
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    expander = DeepSeekQueryExpander(
        api_key=secret,
        model="deepseek-v4-flash",
        opener=opener,
    )

    with pytest.raises(QueryExpansionServiceError) as error:
        expander.expand(query)

    assert str(error.value) == "query expansion service returned HTTP 401"
    assert secret not in str(error.value)
    assert query not in str(error.value)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"search_terms": "cycling"}),
        json.dumps({"search_terms": ["x" * 201]}),
    ],
)
def test_deepseek_expander_rejects_invalid_model_output(content: str) -> None:
    def opener(_request: Request, _timeout: float) -> StubHttpResponse:
        return StubHttpResponse(
            {"choices": [{"message": {"content": content}}]}
        )

    expander = DeepSeekQueryExpander(
        api_key="deepseek-test-secret",
        model="deepseek-v4-flash",
        opener=opener,
    )

    with pytest.raises(
        QueryExpansionServiceError,
        match="query expansion service returned invalid terms",
    ):
        expander.expand("hobby")
