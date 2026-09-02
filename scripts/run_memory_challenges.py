"""Run readable, offline memory challenges against the real retrieval pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Literal, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from aml_memory.metrics import (  # noqa: E402
    RetrievalObservation,
    calculate_metrics,
)
from aml_memory.retrieval import LexicalRetrievalPipeline  # noqa: E402
from aml_memory.schemas import AddRequest, MessageInput, SearchRequest  # noqa: E402
from aml_memory.service import MemoryService  # noqa: E402
from aml_memory.store import MemoryStore  # noqa: E402


@dataclass(frozen=True, slots=True)
class ChallengeMessage:
    role: Literal["user", "assistant"]
    content: str
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class ChallengeSession:
    session_id: str
    messages: tuple[ChallengeMessage, ...]


@dataclass(frozen=True, slots=True)
class ChallengeCase:
    id: str
    title: str
    category: str
    user_id: str
    sessions: tuple[ChallengeSession, ...]
    question: str
    options: tuple[str, ...]
    top_k: int
    required_excerpts: tuple[str, ...]
    forbidden_excerpts: tuple[str, ...]
    expected_first_excerpt: str | None
    expect_empty: bool


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return value


def _list(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-blank string")
    return value


def _optional_string(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label=label)


def _strings(value: object, *, label: str) -> tuple[str, ...]:
    return tuple(
        _string(item, label=f"{label}[{index}]")
        for index, item in enumerate(_list(value, label=label))
    )


def _message(value: object, *, label: str) -> ChallengeMessage:
    record = _object(value, label=label)
    role_value = _string(record.get("role"), label=f"{label}.role")
    if role_value == "user":
        role: Literal["user", "assistant"] = "user"
    elif role_value == "assistant":
        role = "assistant"
    else:
        raise ValueError(f"{label}.role must be user or assistant")
    timestamp_value = record.get("timestamp")
    if timestamp_value is not None and (
        not isinstance(timestamp_value, int) or isinstance(timestamp_value, bool)
    ):
        raise ValueError(f"{label}.timestamp must be an integer or null")
    return ChallengeMessage(
        role=role,
        content=_string(record.get("content"), label=f"{label}.content"),
        timestamp=timestamp_value,
    )


def _session(value: object, *, label: str) -> ChallengeSession:
    record = _object(value, label=label)
    messages = tuple(
        _message(item, label=f"{label}.messages[{index}]")
        for index, item in enumerate(
            _list(record.get("messages"), label=f"{label}.messages")
        )
    )
    if not messages:
        raise ValueError(f"{label}.messages must not be empty")
    return ChallengeSession(
        session_id=_string(record.get("session_id"), label=f"{label}.session_id"),
        messages=messages,
    )


def _case(value: object, *, label: str) -> ChallengeCase:
    record = _object(value, label=label)
    sessions = tuple(
        _session(item, label=f"{label}.sessions[{index}]")
        for index, item in enumerate(
            _list(record.get("sessions"), label=f"{label}.sessions")
        )
    )
    if not sessions:
        raise ValueError(f"{label}.sessions must not be empty")

    top_k = record.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
        raise ValueError(f"{label}.top_k must be an integer from 1 to 100")
    expect_empty = record.get("expect_empty", False)
    if not isinstance(expect_empty, bool):
        raise ValueError(f"{label}.expect_empty must be a boolean")

    return ChallengeCase(
        id=_string(record.get("id"), label=f"{label}.id"),
        title=_string(record.get("title"), label=f"{label}.title"),
        category=_string(record.get("category"), label=f"{label}.category"),
        user_id=_string(record.get("user_id"), label=f"{label}.user_id"),
        sessions=sessions,
        question=_string(record.get("question"), label=f"{label}.question"),
        options=_strings(record.get("options", []), label=f"{label}.options"),
        top_k=top_k,
        required_excerpts=_strings(
            record.get("required_excerpts", []),
            label=f"{label}.required_excerpts",
        ),
        forbidden_excerpts=_strings(
            record.get("forbidden_excerpts", []),
            label=f"{label}.forbidden_excerpts",
        ),
        expected_first_excerpt=_optional_string(
            record.get("expected_first_excerpt"),
            label=f"{label}.expected_first_excerpt",
        ),
        expect_empty=expect_empty,
    )


def load_cases(path: Path) -> list[ChallengeCase]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        _case(item, label=f"cases[{index}]")
        for index, item in enumerate(_list(raw, label="cases"))
    ]
    if not cases:
        raise ValueError("challenge corpus must not be empty")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("challenge case ids must be unique")
    return cases


def _add_case(service: MemoryService, case: ChallengeCase) -> None:
    for index, session in enumerate(case.sessions):
        service.add(
            AddRequest(
                request_id=f"challenge-{case.id}-{index}",
                user_id=case.user_id,
                session_id=session.session_id,
                messages=[
                    MessageInput(
                        role=message.role,
                        timestamp=message.timestamp,
                        content=message.content,
                    )
                    for message in session.messages
                ],
            )
        )


def run_challenges(cases: list[ChallengeCase], *, output: TextIO) -> bool:
    all_passed = True
    observations: list[RetrievalObservation] = []
    with TemporaryDirectory(prefix="aml-memory-challenges-") as temporary_directory:
        store = MemoryStore(Path(temporary_directory) / "memory.db")
        store.initialize()
        service = MemoryService(
            store,
            LexicalRetrievalPipeline(store, neighbor_radius=1),
        )

        for case in cases:
            _add_case(service, case)
            started_at = perf_counter()
            response = service.search(
                SearchRequest(
                    query=case.question,
                    options=list(case.options) or None,
                    user_id=case.user_id,
                    top_k=case.top_k,
                )
            )
            latency_ms = (perf_counter() - started_at) * 1000
            returned = [item.content for item in response.data]
            observations.append(
                RetrievalObservation(
                    required_excerpts=case.required_excerpts,
                    returned_contents=tuple(returned),
                    expect_empty=case.expect_empty,
                    latency_ms=latency_ms,
                )
            )
            print(f"\n[{case.category}] {case.title}", file=output)
            print(f"Question: {case.question}", file=output)
            print("Expected evidence:", file=output)
            for excerpt in case.required_excerpts:
                found = any(excerpt in content for content in returned)
                print(f"  {'FOUND' if found else 'MISSING'}: {excerpt}", file=output)
                all_passed = all_passed and found

            for excerpt in case.forbidden_excerpts:
                absent = not any(excerpt in content for content in returned)
                print(
                    f"  {'FOUND' if absent else 'MISSING'}: excluded {excerpt}",
                    file=output,
                )
                all_passed = all_passed and absent

            if case.expect_empty:
                empty = not returned
                print(
                    f"  {'FOUND' if empty else 'MISSING'}: no supporting evidence",
                    file=output,
                )
                all_passed = all_passed and empty

            if case.expected_first_excerpt is not None:
                first_is_expected = bool(returned) and case.expected_first_excerpt in returned[0]
                print(
                    "  "
                    f"{'FOUND' if first_is_expected else 'MISSING'}: expected evidence first",
                    file=output,
                )
                all_passed = all_passed and first_is_expected

            print("Returned evidence:", file=output)
            if not returned:
                print("  (none)", file=output)
            for index, content in enumerate(returned, start=1):
                print(f"  {index}. {content}", file=output)

    metrics = calculate_metrics(observations)
    print("\nLocal diagnostics (not an official leaderboard score):", file=output)
    print(f"  Recall@K: {metrics.recall_at_k:.3f}", file=output)
    print(f"  MRR: {metrics.mrr:.3f}", file=output)
    print(f"  nDCG: {metrics.ndcg:.3f}", file=output)
    print(f"  Noise rate: {metrics.noise_rate:.3f}", file=output)
    print(f"  Abstention accuracy: {metrics.abstention_accuracy:.3f}", file=output)
    print(f"  Mean latency: {metrics.mean_latency_ms:.2f} ms", file=output)
    print(f"  P95 latency: {metrics.p95_latency_ms:.2f} ms", file=output)

    if all_passed:
        print("\nAll challenge expectations were visible.", file=output)
    else:
        print("\nSome challenge expectations were missing.", file=output)
    return all_passed


def main() -> int:
    if isinstance(sys.stdout, TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "memory_challenges.json",
    )
    args = parser.parse_args()
    return 0 if run_challenges(load_cases(args.cases), output=sys.stdout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
