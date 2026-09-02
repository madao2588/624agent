"""Pluggable text embedding adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
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


def _default_opener(request: Request, timeout: float) -> HttpResponse:
    return cast(HttpResponse, urlopen(request, timeout=timeout))


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
