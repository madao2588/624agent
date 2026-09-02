"""Shared lexical normalization for Latin text and unsegmented CJK text."""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"\w+(?:['-]\w+)*", flags=re.UNICODE)
_CJK_SPLIT_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+|[^\u3400-\u4dbf\u4e00-\u9fff]+")
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def lexical_terms(text: str) -> tuple[str, ...]:
    """Return indexable terms, using overlapping bigrams for CJK runs."""

    terms: list[str] = []
    for match in _WORD_PATTERN.finditer(text):
        for part in _CJK_SPLIT_PATTERN.findall(match.group(0)):
            normalized = part.casefold()
            if _CJK_PATTERN.fullmatch(part) is None:
                terms.append(normalized)
                continue
            if len(normalized) == 1:
                terms.append(normalized)
                continue
            terms.extend(
                normalized[index : index + 2]
                for index in range(len(normalized) - 1)
            )
    return tuple(terms)


def lexical_index_text(text: str) -> str:
    """Build whitespace-delimited content for SQLite's unicode61 tokenizer."""

    return " ".join(lexical_terms(text))
