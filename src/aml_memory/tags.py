"""Deterministic source-message and query-intent classification."""

from __future__ import annotations

import re
from typing import Literal

MemoryTag = Literal["preference", "procedure"]

_MESSAGE_PREFERENCE_PATTERN = re.compile(
    r"\b(?:prefer|preference|favou?r(?:ed|ite)?|love|enjoy|like|dislike|hate|"
    r"avoid|always\s+(?:choose|ask)|can(?:not|'t)\s+stand)\b"
    r"|(?:喜欢|偏爱|最爱|讨厌|不喜欢|避免|总是选择)",
    flags=re.IGNORECASE,
)
_MESSAGE_PROCEDURE_PATTERN = re.compile(
    r"\b(?:must|should|required|need\s+to|before|after|never|do\s+not|"
    r"don't|if|unless|steps?)\b"
    r"|(?:必须|需要|应该|之前|之后|不得|不要|如果|除非|步骤)",
    flags=re.IGNORECASE,
)
_QUERY_PREFERENCE_PATTERN = re.compile(
    r"\b(?:prefer|preference|favou?r(?:ed|ite)?|like|love|enjoy|taste|"
    r"habit|routine|usual(?:ly)?)\b"
    r"|(?:喜欢|偏好|最爱|爱好|讨厌|习惯|通常)",
    flags=re.IGNORECASE,
)
_QUERY_PROCEDURE_PATTERN = re.compile(
    r"\b(?:how\s+(?:do|should|must)|what\s+(?:must|should)|required|procedure|"
    r"process|steps?|rules?|before|after|prerequisite)\b"
    r"|(?:怎么|如何|必须|应该|之前|之后|流程|步骤|规则)",
    flags=re.IGNORECASE,
)


def classify_message(content: str) -> tuple[MemoryTag, ...]:
    tags: list[MemoryTag] = []
    if _MESSAGE_PREFERENCE_PATTERN.search(content) is not None:
        tags.append("preference")
    if _MESSAGE_PROCEDURE_PATTERN.search(content) is not None:
        tags.append("procedure")
    return tuple(tags)


def classify_query(query: str) -> tuple[MemoryTag, ...]:
    tags: list[MemoryTag] = []
    if _QUERY_PREFERENCE_PATTERN.search(query) is not None:
        tags.append("preference")
    if _QUERY_PROCEDURE_PATTERN.search(query) is not None:
        tags.append("procedure")
    return tuple(tags)
