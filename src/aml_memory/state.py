"""Conservative deterministic linking for explicit source-message updates."""

from __future__ import annotations

import re

from aml_memory.lexical import lexical_terms
from aml_memory.models import StoredMessage

_UPDATE_PATTERN = re.compile(
    r"\b(?:changed|moved|rescheduled|postponed|updated|switched|"
    r"cancelled|canceled|no\s+longer|instead)\b"
    r"|(?:改到|改为|改成|调整为|不再|取消|延期|提前)",
    flags=re.IGNORECASE,
)
_STATE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "changed",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "moved",
        "no",
        "not",
        "of",
        "on",
        "or",
        "rescheduled",
        "the",
        "to",
        "updated",
        "was",
        "were",
        "with",
    }
)


def has_explicit_update_signal(content: str) -> bool:
    return _UPDATE_PATTERN.search(content) is not None


def topic_terms(content: str, *, limit: int = 16) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in lexical_terms(content):
        if len(term) < 2 or term in _STATE_STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) == limit:
            break
    return tuple(terms)


def build_state_candidate_query(content: str) -> str | None:
    if not has_explicit_update_signal(content):
        return None
    terms = topic_terms(content)
    if len(terms) < 2:
        return None
    return " OR ".join(f'"{term}"' for term in terms)


def select_superseded_message(
    *,
    content: str,
    occurred_at_ms: int | None,
    candidates: list[StoredMessage],
) -> StoredMessage | None:
    new_terms = set(topic_terms(content))
    eligible: list[StoredMessage] = []
    for candidate in candidates:
        if (
            occurred_at_ms is not None
            and candidate.occurred_at_ms is not None
            and candidate.occurred_at_ms > occurred_at_ms
        ):
            continue
        if len(new_terms.intersection(topic_terms(candidate.content))) < 2:
            continue
        eligible.append(candidate)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda candidate: (
            candidate.occurred_at_ms is not None,
            candidate.occurred_at_ms or 0,
            candidate.sequence,
        ),
    )
