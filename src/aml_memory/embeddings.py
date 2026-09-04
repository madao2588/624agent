"""Pluggable text embedding adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from importlib import import_module
from threading import RLock
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aml_memory.errors import EmbeddingServiceError
from aml_memory.models import EmbeddingBatch


class HttpResponse(Protocol):
    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


HttpOpener = Callable[[Request, float], HttpResponse]

DEFAULT_LOCAL_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
LOCAL_EMBEDDING_BASE_URL = "local://fastembed"


class FastEmbedBackend(Protocol):
    def embed(self, documents: list[str]) -> Iterable[Sequence[float]]: ...


FastEmbedModelFactory = Callable[[str], FastEmbedBackend]


def _default_opener(request: Request, timeout: float) -> HttpResponse:
    return cast(HttpResponse, urlopen(request, timeout=timeout))


def _default_fastembed_model_factory(model_name: str) -> FastEmbedBackend:
    try:
        module = import_module("fastembed")
        constructor = cast(Callable[..., FastEmbedBackend], module.TextEmbedding)
    except (ImportError, AttributeError) as error:
        raise EmbeddingServiceError(
            "local embedding support is unavailable; install the local extra"
        ) from error
    return constructor(model_name=model_name)


class FastEmbedEmbedder:
    """Lazy local embeddings backed by FastEmbed's quantized ONNX runtime."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_LOCAL_EMBEDDING_MODEL,
        model_factory: FastEmbedModelFactory = _default_fastembed_model_factory,
    ) -> None:
        if model != DEFAULT_LOCAL_EMBEDDING_MODEL:
            raise ValueError("local embedding model is not allowlisted")
        self.model = model
        self._model_factory = model_factory
        self._backend: FastEmbedBackend | None = None
        self._lock = RLock()

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding inputs must contain non-blank text")

        backend = self._get_backend()
        try:
            with self._lock:
                vectors = tuple(
                    tuple(float(value) for value in vector)
                    for vector in backend.embed(texts)
                )
            if len(vectors) != len(texts):
                raise ValueError("local embedding count mismatch")
            return EmbeddingBatch(model=self.model, vectors=vectors)
        except EmbeddingServiceError:
            raise
        except Exception as error:
            raise EmbeddingServiceError("local embedding model unavailable") from error

    def _get_backend(self) -> FastEmbedBackend:
        if self._backend is not None:
            return self._backend
        with self._lock:
            if self._backend is not None:
                return self._backend
            try:
                self._backend = self._model_factory(self.model)
            except EmbeddingServiceError:
                raise
            except Exception as error:
                raise EmbeddingServiceError("local embedding model unavailable") from error
            return self._backend


class OpenAICompatibleEmbedder:
    """Synchronous `/embeddings` client implemented with the standard library."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        dimensions: int | None = None,
        timeout_seconds: float = 30.0,
        opener: HttpOpener = _default_opener,
    ) -> None:
        if not api_key.strip():
            raise ValueError("embedding API key must not be blank")
        if not model.strip():
            raise ValueError("embedding model must not be blank")
        if dimensions is not None and dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if timeout_seconds <= 0:
            raise ValueError("embedding timeout must be positive")

        self.model = model
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding inputs must contain non-blank text")

        body: dict[str, Any] = {
            "input": texts,
            "model": self.model,
            "encoding_format": "float",
        }
        if self._dimensions is not None:
            body["dimensions"] = self._dimensions
        request = Request(
            self._endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(request, self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise EmbeddingServiceError(
                f"embedding service returned HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise EmbeddingServiceError("embedding service unavailable") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise EmbeddingServiceError("embedding service returned invalid JSON") from error

        try:
            data = payload["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise ValueError
            ordered: list[tuple[float, ...] | None] = [None] * len(texts)
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError
                index = item["index"]
                vector = item["embedding"]
                if (
                    not isinstance(index, int)
                    or not 0 <= index < len(texts)
                    or ordered[index] is not None
                    or not isinstance(vector, list)
                ):
                    raise ValueError
                ordered[index] = tuple(float(value) for value in vector)
            if any(vector is None for vector in ordered):
                raise ValueError
            vectors = tuple(cast(tuple[float, ...], vector) for vector in ordered)
            batch = EmbeddingBatch(model=self.model, vectors=vectors)
            if self._dimensions is not None and batch.dimensions != self._dimensions:
                raise ValueError
            return batch
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingServiceError("embedding service returned invalid vectors") from error
