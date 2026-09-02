"""Language-model adapters that expand a search query without seeing memories."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from aml_memory.errors import QueryExpansionServiceError

_SYSTEM_PROMPT = """You expand a memory-retrieval query.
Return a JSON object with one key named search_terms and a JSON array of strings.
Generate short search phrases likely to occur verbatim in stored memories.
Always include both Chinese and English cross-language equivalents when the
query is in Chinese or English. Translate the meaning instead of guessing a
personal answer.
Cover relevant identity/name, preference, location, relationship, current or
changed plan, time, negation, and procedure language. For a name question,
include anchors such as name, named, called, 名字, 姓名, and 叫. Preserve useful
entities from the query, return at most 12 terms, never answer the question, and
return JSON only."""
_MAX_TERMS = 12
_MAX_TERM_LENGTH = 200


class HttpResponse(Protocol):
    def __enter__(self) -> HttpResponse: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self) -> bytes: ...


HttpOpener = Callable[[Request, float], HttpResponse]


def _default_opener(request: Request, timeout: float) -> HttpResponse:
    return cast(HttpResponse, urlopen(request, timeout=timeout))


class DeepSeekQueryExpander:
    """Use DeepSeek JSON mode to produce bounded local-search terms."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 30.0,
        opener: HttpOpener = _default_opener,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key must not be blank")
        if not model.strip():
            raise ValueError("DeepSeek model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("query expansion timeout must be positive")
        self.model = model
        self._api_key = api_key
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout_seconds = timeout_seconds
        self._opener = opener

    def expand(self, query: str) -> list[str]:
        if not query.strip():
            raise ValueError("query expansion input must not be blank")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 256,
            "stream": False,
        }
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
            content = payload["choices"][0]["message"]["content"]
            result = json.loads(content)
        except HTTPError as error:
            raise QueryExpansionServiceError(
                f"query expansion service returned HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError) as error:
            raise QueryExpansionServiceError(
                "query expansion service unavailable"
            ) from error
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise QueryExpansionServiceError(
                "query expansion service returned invalid terms"
            ) from error
        return self._validate_terms(result)

    @staticmethod
    def _validate_terms(result: object) -> list[str]:
        try:
            if not isinstance(result, dict):
                raise ValueError
            raw_terms = result["search_terms"]
            if not isinstance(raw_terms, list) or len(raw_terms) > _MAX_TERMS:
                raise ValueError
            terms: list[str] = []
            seen: set[str] = set()
            for raw_term in raw_terms:
                if not isinstance(raw_term, str) or len(raw_term) > _MAX_TERM_LENGTH:
                    raise ValueError
                term = raw_term.strip()
                normalized = term.casefold()
                if not term or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(term)
            return terms
        except (KeyError, ValueError) as error:
            raise QueryExpansionServiceError(
                "query expansion service returned invalid terms"
            ) from error
