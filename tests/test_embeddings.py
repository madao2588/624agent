import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request

import pytest

from aml_memory.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    FastEmbedEmbedder,
    OpenAICompatibleEmbedder,
)
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


class StubFastEmbedModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> object:
        self.calls.append(texts)
        return iter(([1.0, 0.0], [0.0, 1.0])[: len(texts)])


def test_fastembed_embedder_loads_once_and_returns_validated_vectors() -> None:
    model = StubFastEmbedModel()
    factory_calls: list[str] = []

    def factory(model_name: str) -> StubFastEmbedModel:
        factory_calls.append(model_name)
        return model

    embedder = FastEmbedEmbedder(model_factory=factory)

    assert factory_calls == []
    first = embedder.embed(["中文偏好", "English preference"])
    second = embedder.embed(["reuse cached model"])

    assert factory_calls == [DEFAULT_LOCAL_EMBEDDING_MODEL]
    assert model.calls == [
        ["中文偏好", "English preference"],
        ["reuse cached model"],
    ]
    assert first.model == DEFAULT_LOCAL_EMBEDDING_MODEL
    assert first.vectors == ((1.0, 0.0), (0.0, 1.0))
    assert second.vectors == ((1.0, 0.0),)


def test_fastembed_embedder_hides_private_input_when_inference_fails() -> None:
    private_text = "private-local-memory-that-must-not-appear"

    class BrokenModel:
        def embed(self, texts: list[str]) -> object:
            raise RuntimeError(f"failed on {texts[0]}")

    embedder = FastEmbedEmbedder(model_factory=lambda _model_name: BrokenModel())

    with pytest.raises(EmbeddingServiceError) as error:
        embedder.embed([private_text])

    assert str(error.value) == "local embedding model unavailable"
    assert private_text not in str(error.value)


def test_fastembed_embedder_serializes_shared_backend_inference() -> None:
    state_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0

    class ConcurrencyProbeModel:
        def embed(self, texts: list[str]) -> object:
            def vectors() -> object:
                nonlocal active_calls, max_active_calls
                with state_lock:
                    active_calls += 1
                    max_active_calls = max(max_active_calls, active_calls)
                time.sleep(0.02)
                with state_lock:
                    active_calls -= 1
                yield (1.0, 0.0)

            return vectors()

    embedder = FastEmbedEmbedder(
        model_factory=lambda _model_name: ConcurrencyProbeModel()
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        batches = list(executor.map(lambda text: embedder.embed([text]), ["a", "b"]))

    assert [batch.vectors for batch in batches] == [((1.0, 0.0),), ((1.0, 0.0),)]
    assert max_active_calls == 1


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
