"""Conservative local annotations used only to retrieve source messages."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from aml_memory.models import FacetKind, MemoryFacet, MessageAnalysis

_SPACE_PATTERN = re.compile(r"\s+")
_ENGLISH_ENTITY_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9'-]{1,}"
    r"(?:\s+[A-Z][A-Za-z0-9'-]{1,}){0,2}\b"
)
_ENGLISH_ALIAS_PATTERN = re.compile(
    r"(?P<left>[A-Z][A-Za-z0-9'-]{1,}(?:\s+[A-Z][A-Za-z0-9'-]{1,}){0,2})"
    r"\s*,?\s*(?:also\s+known\s+as|aka|also\s+called)\s+"
    r"(?P<right>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 .'-]{0,30})",
    flags=re.IGNORECASE,
)
_CJK_ALIAS_PATTERN = re.compile(
    r"(?P<left>[\u4e00-\u9fff]{1,8}|[A-Z][A-Za-z0-9 .'-]{1,30})"
    r"\s*(?:就是|也叫|又叫)\s*"
    r"(?P<right>[\u4e00-\u9fff]{1,8}|[A-Z][A-Za-z0-9 .'-]{1,30})"
)
_CJK_PERSON_PATTERN = re.compile(r"[\u4e00-\u9fff]{1,4}(?:老师|医生|教授)")
_CJK_PLACE_PATTERN = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9·-]{1,8}"
    r"(?:咖啡馆|咖啡店|餐厅|公园|学校|医院|大厦|广场|湖|河)"
)
_ENGLISH_PLACE_SUFFIXES = (
    " cafe",
    " coffee",
    " park",
    " lake",
    " river",
    " restaurant",
    " hospital",
    " school",
    " room",
)
_ENTITY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "after",
        "before",
        "he",
        "her",
        "hers",
        "his",
        "i",
        "if",
        "it",
        "its",
        "my",
        "she",
        "the",
        "their",
        "they",
        "this",
        "today",
        "tomorrow",
        "unless",
        "we",
        "yesterday",
    }
)
_PERSON_PRONOUN_PATTERN = re.compile(
    r"\b(?:he|she|him|her|they|them|his|hers|their)\b|(?:他|她|他们|她们)",
    flags=re.IGNORECASE,
)
_PLACE_PRONOUN_PATTERN = re.compile(r"\bthere\b|(?:那里|那儿|原地点)", re.IGNORECASE)
_ISO_DATE_PATTERN = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_EVENT_PATTERN = re.compile(
    r"\b(?:appointment|meeting|briefing|launch|trip|visit|interview|deadline)\b"
    r"|(?:见面|会议|约会|复诊|发布会|行程|拜访|面试|截止时间)",
    flags=re.IGNORECASE,
)
_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cancel",
        re.compile(r"\b(?:cancelled|canceled|called\s+off)\b|(?:取消|作废)", re.I),
    ),
    (
        "resume",
        re.compile(
            r"\b(?:resumed|restored|back\s+on|reinstated)\b|(?:恢复|重新开始|照常)",
            re.I,
        ),
    ),
    (
        "forget",
        re.compile(r"\b(?:forget|forgot|delete\s+the\s+memory)\b|(?:忘记|遗忘|删除记忆)", re.I),
    ),
    (
        "update",
        re.compile(
            r"\b(?:changed|moved|rescheduled|postponed|updated|switched|now)\b"
            r"|(?:改到|改为|改成|调整为|延期|提前|现在)",
            re.I,
        ),
    ),
)
_PREFERENCE_PATTERN = re.compile(
    r"\b(?:prefers?|favou?rite|loves?|likes?|enjoys?|chooses?)\b"
    r"|(?:喜欢|偏爱|最爱|选择)",
    re.I,
)
_AVERSION_PATTERN = re.compile(
    r"\b(?:avoid|dislike|hate|cannot\s+stand|can't\s+stand)\b"
    r"|(?:避免|讨厌|不喜欢)",
    re.I,
)
_HABIT_PATTERN = re.compile(
    r"\b(?:always|usually|often|every\s+(?:day|week|time))\b"
    r"|(?:总是|通常|经常|每次|每天|每周)",
    re.I,
)
_ONE_OFF_PATTERN = re.compile(
    r"\b(?:once|one\s+time|yesterday|just\s+this\s+time|tried)\b"
    r"|(?:一次|昨天|这一次|这次|尝鲜)",
    re.I,
)
_RULE_CONDITION_PATTERN = re.compile(r"\b(?:if|when|provided\s+that)\b|(?:如果|若|当)", re.I)
_RULE_EXCEPTION_PATTERN = re.compile(r"\b(?:unless|except)\b|(?:除非|例外)", re.I)
_RULE_REQUIREMENT_PATTERN = re.compile(
    r"\b(?:must|required|need\s+to|should|shall)\b|(?:必须|需要|应该|务必)",
    re.I,
)
_RULE_PROHIBITION_PATTERN = re.compile(
    r"\b(?:never|must\s+not|do\s+not|don't|prohibited)\b"
    r"|(?:不得|不要|禁止|严禁)",
    re.I,
)
_RULE_ORDER_PATTERN = re.compile(
    r"\b(?:before|after|first|then)\b|(?:之前|之后|先.+再|首先|然后)",
    re.I,
)
_PROMPT_INJECTION_PATTERN = re.compile(
    r"\b(?:ignore|disregard)\s+(?:all\s+)?previous\s+instructions\b"
    r"|\b(?:system\s+prompt|answer\s+that|reveal\s+(?:the\s+)?secret)\b"
    r"|(?:忽略|无视)(?:之前|以上|所有)?(?:的)?指令|(?:系统提示词|泄露密钥)",
    re.I,
)


def normalize_facet_value(value: str) -> str:
    punctuation = " \t\r\n.,;:!?\uff0c\u3002\uff1b\uff1a\uff01\uff1f()\uff08\uff09[]{}\"'"
    return _SPACE_PATTERN.sub(" ", value.strip(punctuation)).casefold()


def _facet(kind: FacetKind, value: str, confidence: float) -> MemoryFacet | None:
    normalized = normalize_facet_value(value)
    if not normalized:
        return None
    return MemoryFacet(
        kind=kind,
        value=value.strip(),
        normalized_value=normalized,
        confidence=confidence,
    )


def _add(
    facets: list[MemoryFacet],
    seen: set[tuple[FacetKind, str]],
    kind: FacetKind,
    value: str,
    confidence: float,
) -> None:
    facet = _facet(kind, value, confidence)
    if facet is None:
        return
    key = (facet.kind, facet.normalized_value)
    if key in seen:
        return
    seen.add(key)
    facets.append(facet)


def _extract_aliases(
    content: str,
    facets: list[MemoryFacet],
    seen: set[tuple[FacetKind, str]],
) -> None:
    for pattern in (_ENGLISH_ALIAS_PATTERN, _CJK_ALIAS_PATTERN):
        for match in pattern.finditer(content):
            for value in (match.group("left"), match.group("right")):
                cleaned = value.strip(" ,\uff0c\u3002")
                _add(facets, seen, "entity", cleaned, 0.98)
                _add(facets, seen, "alias", cleaned, 0.98)


def _extract_entities_and_places(
    content: str,
    facets: list[MemoryFacet],
    seen: set[tuple[FacetKind, str]],
) -> None:
    for match in _ENGLISH_ENTITY_PATTERN.finditer(content):
        value = re.sub(r"^(?:the|a|an)\s+", "", match.group(0), flags=re.IGNORECASE)
        normalized = normalize_facet_value(value)
        if normalized in _ENTITY_STOPWORDS:
            continue
        _add(facets, seen, "entity", value, 0.9)
        if normalized.endswith(_ENGLISH_PLACE_SUFFIXES):
            _add(facets, seen, "place", value, 0.95)
    for match in _CJK_PERSON_PATTERN.finditer(content):
        value = match.group(0).lstrip("和与跟请找")
        _add(facets, seen, "entity", value, 0.9)
    for match in _CJK_PLACE_PATTERN.finditer(content):
        value = match.group(0).lstrip("在去到和与")
        _add(facets, seen, "entity", value, 0.85)
        _add(facets, seen, "place", value, 0.92)


def _resolved_dates(content: str, occurred_at_ms: int | None) -> list[tuple[str, str]]:
    dates = [(match.group(0), match.group(0)) for match in _ISO_DATE_PATTERN.finditer(content)]
    if occurred_at_ms is None:
        return dates
    base = datetime.fromtimestamp(occurred_at_ms / 1000, tz=UTC)
    relative_days = (
        (re.compile(r"\bday\s+after\s+tomorrow\b|后天", re.I), 2),
        (re.compile(r"\btomorrow\b|明天", re.I), 1),
        (re.compile(r"\byesterday\b|昨天", re.I), -1),
        (re.compile(r"\btoday\b|今天", re.I), 0),
        (re.compile(r"\btwo\s+days\s+later\b|两天后", re.I), 2),
    )
    for pattern, offset in relative_days:
        for match in pattern.finditer(content):
            resolved = (base + timedelta(days=offset)).date().isoformat()
            dates.append((match.group(0), resolved))
    weekday_names = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    for match in re.finditer(r"下周([一二三四五六日天])", content):
        week_start = base.date() - timedelta(days=base.weekday())
        resolved_date = week_start + timedelta(days=7 + weekday_names[match.group(1)])
        dates.append((match.group(0), resolved_date.isoformat()))
    return dates


def analyze_message(content: str, *, occurred_at_ms: int | None) -> MessageAnalysis:
    facets: list[MemoryFacet] = []
    seen: set[tuple[FacetKind, str]] = set()
    _extract_aliases(content, facets, seen)
    _extract_entities_and_places(content, facets, seen)

    for raw_value, resolved in _resolved_dates(content, occurred_at_ms):
        _add(facets, seen, "time_expression", raw_value, 1.0)
        _add(facets, seen, "date", resolved, 1.0)
    for match in _EVENT_PATTERN.finditer(content):
        _add(facets, seen, "event", match.group(0), 0.9)
    for status, pattern in _STATUS_PATTERNS:
        if pattern.search(content) is not None and (
            status != "update" or _EVENT_PATTERN.search(content) is not None
        ):
            _add(facets, seen, "event_status", status, 0.95)
            break

    if _PREFERENCE_PATTERN.search(content) is not None:
        _add(facets, seen, "preference", content, 0.85)
    if _AVERSION_PATTERN.search(content) is not None:
        _add(facets, seen, "aversion", content, 0.9)
    if _HABIT_PATTERN.search(content) is not None:
        _add(facets, seen, "habit", content, 0.95)
    if _ONE_OFF_PATTERN.search(content) is not None:
        _add(facets, seen, "one_off", content, 0.9)

    has_condition = _RULE_CONDITION_PATTERN.search(content) is not None
    if has_condition:
        _add(facets, seen, "rule_condition", content, 0.9)
    if _RULE_REQUIREMENT_PATTERN.search(content) is not None or (
        has_condition and _RULE_ORDER_PATTERN.search(content) is not None
    ):
        _add(facets, seen, "rule_requirement", content, 0.85)
    if _RULE_PROHIBITION_PATTERN.search(content) is not None:
        _add(facets, seen, "rule_prohibition", content, 0.95)
    if _RULE_ORDER_PATTERN.search(content) is not None:
        _add(facets, seen, "rule_order", content, 0.9)
    if _RULE_EXCEPTION_PATTERN.search(content) is not None:
        _add(facets, seen, "rule_exception", content, 0.95)
    if _PROMPT_INJECTION_PATTERN.search(content) is not None:
        _add(facets, seen, "safety", "prompt-injection", 1.0)
    return MessageAnalysis(facets=tuple(facets))


def analyze_batch(
    items: list[tuple[str, int | None]],
) -> tuple[MessageAnalysis, ...]:
    analyses: list[MessageAnalysis] = []
    prior_entities: tuple[MemoryFacet, ...] = ()
    prior_places: tuple[MemoryFacet, ...] = ()
    for content, occurred_at_ms in items:
        base = analyze_message(content, occurred_at_ms=occurred_at_ms)
        facets = list(base.facets)
        seen = {(facet.kind, facet.normalized_value) for facet in facets}
        if _PERSON_PRONOUN_PATTERN.search(content) is not None and prior_entities:
            inherited = prior_entities[0]
            _add(facets, seen, "entity", inherited.value, 0.65)
            _add(facets, seen, "coreference", inherited.value, 0.65)
        if _PLACE_PRONOUN_PATTERN.search(content) is not None and len(prior_places) == 1:
            inherited_place = prior_places[0]
            _add(facets, seen, "place", inherited_place.value, 0.65)
            _add(facets, seen, "coreference", inherited_place.value, 0.65)
        analysis = MessageAnalysis(facets=tuple(facets))
        analyses.append(analysis)
        explicit_entities = tuple(
            facet
            for facet in base.facets
            if facet.kind == "entity" and facet.confidence >= 0.85
        )
        explicit_places = tuple(
            facet
            for facet in base.facets
            if facet.kind == "place" and facet.confidence >= 0.85
        )
        if explicit_entities:
            prior_entities = explicit_entities
        if explicit_places:
            prior_places = explicit_places
    return tuple(analyses)
