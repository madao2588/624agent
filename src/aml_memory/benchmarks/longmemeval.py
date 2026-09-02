"""Dependency-free LongMemEval dataset adaptation and retrieval metrics."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from aml_memory.models import ScoredMessage
from aml_memory.schemas import AddRequest, MessageInput

QuestionType = Literal[
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "temporal-reasoning",
    "knowledge-update",
    "multi-session",
]
Role = Literal["user", "assistant"]

_QUESTION_TYPES = {
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "temporal-reasoning",
    "knowledge-update",
    "multi-session",
}
_DATE_PATTERN = re.compile(
    r"^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})"
    r"(?:\s+\([^)]+\))?(?:\s+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?$"
)


@dataclass(frozen=True, slots=True)
class LongMemEvalTurn:
    role: Role
    content: str
    has_answer: bool


@dataclass(frozen=True, slots=True)
class LongMemEvalSession:
    session_id: str
    date: str
    occurred_at_ms: int
    turns: tuple[LongMemEvalTurn, ...]


@dataclass(frozen=True, slots=True)
class LongMemEvalCase:
    question_id: str
    question_type: QuestionType
    question: str
    answer: str
    question_date: str
    question_occurred_at_ms: int
    sessions: tuple[LongMemEvalSession, ...]
    answer_session_ids: tuple[str, ...]

    @property
    def is_abstention(self) -> bool:
        return self.question_id.endswith("_abs")

    @property
    def answer_turn_ids(self) -> tuple[str, ...]:
        return tuple(
            f"{session.session_id}_{ordinal + 1}"
            for session in self.sessions
            for ordinal, turn in enumerate(session.turns)
            if turn.has_answer
        )


@dataclass(frozen=True, slots=True)
class SourceBinding:
    request_id: str
    ordinal: int
    turn_id: str


@dataclass(frozen=True, slots=True)
class IngestionPlan:
    requests: tuple[AddRequest, ...]
    source_bindings: tuple[SourceBinding, ...]


@dataclass(frozen=True, slots=True)
class RankedEvidence:
    turn_ids: tuple[str, ...]
    session_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalAtK:
    recall_any: float
    recall_all: float
    ndcg: float


@dataclass(frozen=True, slots=True)
class CaseRetrievalMetrics:
    question_id: str
    question_type: QuestionType
    skipped: bool
    session: Mapping[int, RetrievalAtK]
    turn: Mapping[int, RetrievalAtK]


def parse_longmemeval_date(value: str) -> int:
    """Parse the benchmark's English-weekday timestamp without locale state."""

    match = _DATE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"unsupported LongMemEval date: {value!r}")
    try:
        parsed = datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour") or 0),
            int(match.group("minute") or 0),
            tzinfo=UTC,
        )
    except ValueError as error:
        raise ValueError(f"unsupported LongMemEval date: {value!r}") from error
    return int(parsed.timestamp() * 1000)


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    return value


def _array(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-blank string")
    return value


def _answer_text(value: object, *, label: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return _string(value, label=label)


def _content_text(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _strings(value: object, *, label: str) -> tuple[str, ...]:
    return tuple(
        _string(item, label=f"{label}[{index}]")
        for index, item in enumerate(_array(value, label=label))
    )


def _parse_turn(value: object, *, label: str) -> LongMemEvalTurn:
    record = _object(value, label=label)
    raw_role = _string(record.get("role"), label=f"{label}.role")
    if raw_role not in {"user", "assistant"}:
        raise ValueError(f"{label}.role must be user or assistant")
    has_answer = record.get("has_answer", False)
    if not isinstance(has_answer, bool):
        raise ValueError(f"{label}.has_answer must be a boolean")
    role: Role = "user" if raw_role == "user" else "assistant"
    return LongMemEvalTurn(
        role=role,
        content=_content_text(record.get("content"), label=f"{label}.content"),
        has_answer=has_answer,
    )


def _parse_case(value: object, *, index: int) -> LongMemEvalCase:
    label = f"cases[{index}]"
    record = _object(value, label=label)
    question_id = _string(record.get("question_id"), label=f"{label}.question_id")
    label = f"case {question_id}"
    raw_question_type = _string(
        record.get("question_type"), label=f"{label}.question_type"
    )
    if raw_question_type not in _QUESTION_TYPES:
        raise ValueError(f"{label}.question_type is not supported: {raw_question_type!r}")
    question_type: QuestionType = raw_question_type  # type: ignore[assignment]

    session_ids = _strings(
        record.get("haystack_session_ids"), label=f"{label}.haystack_session_ids"
    )
    dates = _strings(record.get("haystack_dates"), label=f"{label}.haystack_dates")
    raw_sessions = _array(
        record.get("haystack_sessions"), label=f"{label}.haystack_sessions"
    )
    if not session_ids:
        raise ValueError(f"{label} session ids must not be empty")
    if len(session_ids) != len(dates) or len(session_ids) != len(raw_sessions):
        raise ValueError(
            f"{label} parallel arrays haystack_session_ids, haystack_dates, and "
            "haystack_sessions must have equal lengths"
        )

    sessions: list[LongMemEvalSession] = []
    for session_index, (session_id, date, raw_session) in enumerate(
        zip(session_ids, dates, raw_sessions, strict=True)
    ):
        raw_turns = _array(
            raw_session, label=f"{label}.haystack_sessions[{session_index}]"
        )
        if not raw_turns:
            raise ValueError(f"{label}.haystack_sessions[{session_index}] must not be empty")
        sessions.append(
            LongMemEvalSession(
                session_id=session_id,
                date=date,
                occurred_at_ms=parse_longmemeval_date(date),
                turns=tuple(
                    _parse_turn(
                        turn,
                        label=(
                            f"{label}.haystack_sessions[{session_index}][{turn_index}]"
                        ),
                    )
                    for turn_index, turn in enumerate(raw_turns)
                ),
            )
        )

    answer_session_ids = _strings(
        record.get("answer_session_ids"), label=f"{label}.answer_session_ids"
    )
    unknown_answer_ids = set(answer_session_ids).difference(session_ids)
    if unknown_answer_ids:
        raise ValueError(
            f"{label}.answer_session_ids contains unknown sessions: "
            f"{sorted(unknown_answer_ids)!r}"
        )

    question_date = _string(
        record.get("question_date"), label=f"{label}.question_date"
    )
    parsed = LongMemEvalCase(
        question_id=question_id,
        question_type=question_type,
        question=_string(record.get("question"), label=f"{label}.question"),
        answer=_answer_text(record.get("answer"), label=f"{label}.answer"),
        question_date=question_date,
        question_occurred_at_ms=parse_longmemeval_date(question_date),
        sessions=tuple(sessions),
        answer_session_ids=answer_session_ids,
    )
    if not parsed.is_abstention and not parsed.answer_session_ids:
        raise ValueError(f"{label} must identify at least one answer session")
    if not parsed.is_abstention and not parsed.answer_turn_ids:
        raise ValueError(f"{label} must label at least one answer turn")
    if any(
        turn.has_answer and not turn.content.strip()
        for session in parsed.sessions
        for turn in session.turns
    ):
        raise ValueError(f"{label} must not label a blank turn as answer evidence")
    return parsed


def _iter_json_array(path: Path, *, chunk_size: int) -> Iterator[object]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as source:
        buffer = ""
        position = 0
        eof = False

        def fill() -> None:
            nonlocal buffer, position, eof
            if position:
                buffer = buffer[position:]
                position = 0
            chunk = source.read(chunk_size)
            if chunk:
                buffer += chunk
            else:
                eof = True

        def skip_whitespace() -> None:
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or eof:
                    return
                fill()

        fill()
        skip_whitespace()
        if position >= len(buffer) or buffer[position] != "[":
            raise ValueError(f"{path} must contain a JSON array")
        position += 1
        first = True

        while True:
            skip_whitespace()
            if position >= len(buffer):
                raise ValueError(f"{path} contains an unterminated JSON array")
            if buffer[position] == "]":
                position += 1
                break
            if not first:
                if buffer[position] != ",":
                    raise ValueError(f"{path} must separate array items with commas")
                position += 1
                skip_whitespace()
                if position < len(buffer) and buffer[position] == "]":
                    raise ValueError(f"{path} must not contain a trailing comma")

            while True:
                try:
                    value, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError as error:
                    if eof:
                        raise ValueError(f"invalid JSON in {path}: {error.msg}") from error
                    fill()
                else:
                    position = end
                    yield value
                    first = False
                    break

        skip_whitespace()
        if position < len(buffer) or (not eof and source.read(1)):
            raise ValueError(f"{path} contains content after the JSON array")


def iter_longmemeval_cases(
    path: Path, *, chunk_size: int = 1024 * 1024
) -> Iterator[LongMemEvalCase]:
    """Stream and validate official LongMemEval instances from a JSON array."""

    seen: set[str] = set()
    count = 0
    for index, value in enumerate(_iter_json_array(path, chunk_size=chunk_size)):
        case = _parse_case(value, index=index)
        if case.question_id in seen:
            raise ValueError(f"duplicate LongMemEval question id: {case.question_id}")
        seen.add(case.question_id)
        count += 1
        yield case
    if count == 0:
        raise ValueError("LongMemEval dataset must not be empty")


def _estimated_words(content: str) -> int:
    return max(len(content.split()), math.ceil(len(content) / 4))


def _chunk_session_turns(
    turns: Sequence[LongMemEvalTurn],
    *,
    max_messages: int,
    max_words: int,
) -> Iterator[tuple[tuple[int, LongMemEvalTurn], ...]]:
    chunk: list[tuple[int, LongMemEvalTurn]] = []
    chunk_words = 0
    for source_ordinal, turn in enumerate(turns):
        if not turn.content.strip():
            continue
        turn_words = _estimated_words(turn.content)
        if chunk and (
            len(chunk) >= max_messages or chunk_words + turn_words > max_words
        ):
            yield tuple(chunk)
            chunk = []
            chunk_words = 0
        chunk.append((source_ordinal, turn))
        chunk_words += turn_words
    if chunk:
        yield tuple(chunk)


def build_ingestion_plan(
    case: LongMemEvalCase,
    *,
    max_messages: int = 20,
    max_words: int = 2_000,
) -> IngestionPlan:
    """Create stable Add requests and source-turn bindings for one case."""

    if max_messages < 1 or max_words < 1:
        raise ValueError("ingestion limits must be positive")
    requests: list[AddRequest] = []
    bindings: list[SourceBinding] = []
    user_id = f"longmemeval:{case.question_id}"

    for session_index, session in enumerate(case.sessions):
        for chunk_index, chunk in enumerate(
            _chunk_session_turns(
                session.turns,
                max_messages=max_messages,
                max_words=max_words,
            )
        ):
            request_id = (
                f"longmemeval-{case.question_id}-{session_index}-{chunk_index}"
            )
            requests.append(
                AddRequest(
                    request_id=request_id,
                    user_id=user_id,
                    session_id=session.session_id,
                    messages=[
                        MessageInput(
                            role=turn.role,
                            timestamp=session.occurred_at_ms,
                            content=turn.content,
                        )
                        for _, turn in chunk
                    ],
                )
            )
            bindings.extend(
                SourceBinding(
                    request_id=request_id,
                    ordinal=local_ordinal,
                    turn_id=f"{session.session_id}_{source_ordinal + 1}",
                )
                for local_ordinal, (source_ordinal, _) in enumerate(chunk)
            )

    return IngestionPlan(requests=tuple(requests), source_bindings=tuple(bindings))


def build_add_requests(
    case: LongMemEvalCase,
    *,
    max_messages: int = 20,
    max_words: int = 2_000,
) -> tuple[AddRequest, ...]:
    return build_ingestion_plan(
        case,
        max_messages=max_messages,
        max_words=max_words,
    ).requests


def rank_scored_messages(
    plan: IngestionPlan, results: Sequence[ScoredMessage]
) -> RankedEvidence:
    """Map stored message identities back to official source identities."""

    turn_by_stored_identity = {
        (binding.request_id, binding.ordinal): binding.turn_id
        for binding in plan.source_bindings
    }
    turn_ids: list[str] = []
    session_ids: list[str] = []
    seen_turns: set[str] = set()
    seen_sessions: set[str] = set()
    for result in results:
        stored_identity = (result.message.request_id, result.message.ordinal)
        try:
            turn_id = turn_by_stored_identity[stored_identity]
        except KeyError as error:
            raise ValueError(
                "retrieval returned a message outside the LongMemEval ingestion plan"
            ) from error
        if turn_id not in seen_turns:
            seen_turns.add(turn_id)
            turn_ids.append(turn_id)
        if result.message.session_id not in seen_sessions:
            seen_sessions.add(result.message.session_id)
            session_ids.append(result.message.session_id)
    return RankedEvidence(turn_ids=tuple(turn_ids), session_ids=tuple(session_ids))


def _official_dcg(relevances: Sequence[int]) -> float:
    if not relevances:
        return 0.0
    return float(relevances[0]) + sum(
        relevance / math.log2(rank)
        for rank, relevance in enumerate(relevances[1:], start=2)
    )


def _evaluate_at_k(
    ranked_ids: Sequence[str], correct_ids: Sequence[str], *, k: int
) -> RetrievalAtK:
    correct = set(correct_ids)
    top_ids = tuple(ranked_ids[:k])
    recalled = set(top_ids)
    relevances = [int(item in correct) for item in top_ids]
    ideal = [1] * min(len(correct), k)
    ideal.extend([0] * max(0, len(top_ids) - len(ideal)))
    ideal_gain = _official_dcg(ideal)
    return RetrievalAtK(
        recall_any=float(bool(correct.intersection(recalled))),
        recall_all=float(correct.issubset(recalled)),
        ndcg=(_official_dcg(relevances) / ideal_gain if ideal_gain else 0.0),
    )


def evaluate_ranked_evidence(
    case: LongMemEvalCase,
    ranked: RankedEvidence,
    *,
    cutoffs: Sequence[int],
) -> CaseRetrievalMetrics:
    """Apply LongMemEval-style formulas to one all-role service ranking."""

    normalized_cutoffs = tuple(sorted(set(cutoffs)))
    if not normalized_cutoffs or normalized_cutoffs[0] < 1:
        raise ValueError("cutoffs must contain positive integers")
    if case.is_abstention:
        return CaseRetrievalMetrics(
            question_id=case.question_id,
            question_type=case.question_type,
            skipped=True,
            session={},
            turn={},
        )
    return CaseRetrievalMetrics(
        question_id=case.question_id,
        question_type=case.question_type,
        skipped=False,
        session={
            k: _evaluate_at_k(ranked.session_ids, case.answer_session_ids, k=k)
            for k in normalized_cutoffs
        },
        turn={
            k: _evaluate_at_k(ranked.turn_ids, case.answer_turn_ids, k=k)
            for k in normalized_cutoffs
        },
    )
