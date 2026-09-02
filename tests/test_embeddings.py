import json
from urllib.request import Request

import pytest

from aml_memory.embeddings import OpenAICompatibleEmbedder
from aml_memory.errors import EmbeddingServiceError


class StubHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "StubHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_openai_compatible_embedder_batches_inputs_and_restores_index_order() -> None:
    captured: dict[str, object] = {}

    def opener(request: Request, timeout: float) -> StubHttpResponse:
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        captured["body"] = json.loads(bytes(request.data or b"{}").decode("utf-8"))
        return StubHttpResponse(
            {
                "object": "list",
                "model": "text-embedding-test",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0]},
                ],
            }
        )

    embedder = OpenAICompatibleEmbedder(
        api_key="test-secret",
        model="text-embedding-test",
        base_url="https://embedding.example/v1/",
        dimensions=2,
        timeout_seconds=7.5,
        opener=opener,
    )

    batch = embedder.embed(["first", "second"])

    assert batch.model == "text-embedding-test"
    assert batch.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert captured == {
        "url": "https://embedding.example/v1/embeddings",
        "authorization": "Bearer test-secret",
        "timeout": 7.5,
        "body": {
            "input": ["first", "second"],
            "model": "text-embedding-test",
            "encoding_format": "float",
            "dimensions": 2,
        },
    }


def test_openai_compatible_embedder_rejects_malformed_response_without_echoing_input() -> None:
    private_text = "private-memory-that-must-not-appear"

    def opener(_request: Request, _timeout: float) -> StubHttpResponse:
        return StubHttpResponse({"object": "list", "data": []})

    embedder = OpenAICompatibleEmbedder(
        api_key="test-secret",
        model="text-embedding-test",
        base_url="https://embedding.example/v1",
        opener=opener,
    )

    with pytest.raises(EmbeddingServiceError) as error:
        embedder.embed([private_text])

    assert private_text not in str(error.value)
    assert "test-secret" not in str(error.value)
