import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aml_memory.benchmarks.longmemeval import (
    RankedEvidence,
    build_add_requests,
    build_ingestion_plan,
    evaluate_ranked_evidence,
    iter_longmemeval_cases,
    parse_longmemeval_date,
)
from aml_memory.retrieval import LexicalRetrievalPipeline
from aml_memory.schemas import SearchRequest
from aml_memory.service import MemoryService
from aml_memory.store import MemoryStore

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "longmemeval_tiny.json"


def test_official_shaped_fixture_streams_without_loading_contract_shortcuts() -> None:
    cases = list(iter_longmemeval_cases(FIXTURE_PATH, chunk_size=37))

    assert [case.question_id for case in cases] == [
        "tiny-single-user",
        "tiny-unknown_abs",
    ]
    assert cases[0].answer_session_ids == ("evidence-session",)
    assert cases[0].answer_turn_ids == ("evidence-session_1",)
    assert cases[1].is_abstention is True
    assert cases[0].sessions[0].occurred_at_ms == int(
        datetime(2023, 5, 1, 10, 30, tzinfo=UTC).timestamp() * 1000
    )


def test_longmemeval_date_parser_is_locale_independent() -> None:
    assert parse_longmemeval_date("2023/05/01 (Mon) 10:30") == int(
        datetime(2023, 5, 1, 10, 30, tzinfo=UTC).timestamp() * 1000
    )
    assert parse_longmemeval_date("2023/5/1") == int(
        datetime(2023, 5, 1, tzinfo=UTC).timestamp() * 1000
    )

    with pytest.raises(ValueError, match="unsupported LongMemEval date"):
        parse_longmemeval_date("next Tuesday")


def test_parallel_session_arrays_are_validated_with_the_question_id(tmp_path: Path) -> None:
    malformed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[:1]
    malformed[0]["haystack_dates"] = []
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps(malformed), encoding="utf-8")

    with pytest.raises(ValueError, match=r"tiny-single-user.*parallel arrays"):
        list(iter_longmemeval_cases(path))


def test_duplicate_official_session_ids_are_preserved_as_separate_occurrences(
    tmp_path: Path,
) -> None:
    duplicated = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[:1]
    duplicated[0]["haystack_session_ids"].append("filler-session")
    duplicated[0]["haystack_dates"].append("2023/05/02 (Tue) 10:30")
    duplicated[0]["haystack_sessions"].append(
        duplicated[0]["haystack_sessions"][0]
    )
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps(duplicated), encoding="utf-8")

    case = next(iter_longmemeval_cases(path))

    assert [session.session_id for session in case.sessions].count("filler-session") == 2
    assert len(build_add_requests(case)) == 3


def test_numeric_official_answers_are_normalized_for_future_readers(
    tmp_path: Path,
) -> None:
    numeric = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[:1]
    numeric[0]["answer"] = 3
    path = tmp_path / "numeric-answer.json"
    path.write_text(json.dumps(numeric), encoding="utf-8")

    case = next(iter_longmemeval_cases(path))

    assert case.answer == "3"


def test_blank_filler_turn_is_not_ingested_and_does_not_renumber_sources(
    tmp_path: Path,
) -> None:
    blank_turn = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[:1]
    blank_turn[0]["haystack_sessions"][1].insert(
        0,
        {"role": "user", "content": ""},
    )
    path = tmp_path / "blank-turn.json"
    path.write_text(json.dumps(blank_turn), encoding="utf-8")

    case = next(iter_longmemeval_cases(path))
    plan = build_ingestion_plan(case)

    assert case.answer_turn_ids == ("evidence-session_2",)
    assert all(message.content for request in plan.requests for message in request.messages)
    assert {binding.turn_id for binding in plan.source_bindings} >= {
        "evidence-session_2",
        "evidence-session_3",
    }
    assert "evidence-session_1" not in {
        binding.turn_id for binding in plan.source_bindings
    }


def test_add_requests_keep_source_session_identity_across_safe_chunks() -> None:
    case = next(iter_longmemeval_cases(FIXTURE_PATH))

    requests = build_add_requests(case, max_messages=1, max_words=2_000)

    evidence_requests = [
        request for request in requests if request.session_id == "evidence-session"
    ]
    assert len(evidence_requests) == 2
    assert [request.request_id for request in evidence_requests] == [
        "longmemeval-tiny-single-user-1-0",
        "longmemeval-tiny-single-user-1-1",
    ]
    assert all(request.user_id == "longmemeval:tiny-single-user" for request in requests)
    assert all(request.session_id == "evidence-session" for request in evidence_requests)
    assert evidence_requests[0].messages[0].timestamp == case.sessions[1].occurred_at_ms


def test_official_style_metrics_score_sessions_and_turns_separately() -> None:
    case = next(iter_longmemeval_cases(FIXTURE_PATH))
    ranked = RankedEvidence(
        turn_ids=("filler-session_1", "other-session_1", "evidence-session_1"),
        session_ids=("filler-session", "other-session", "evidence-session"),
    )

    metrics = evaluate_ranked_evidence(case, ranked, cutoffs=(1, 3))

    assert metrics.skipped is False
    assert metrics.session[1].recall_any == 0.0
    assert metrics.session[3].recall_any == 1.0
    assert metrics.session[3].recall_all == 1.0
    assert metrics.session[3].ndcg == pytest.approx(1 / 1.584962500721156)
    assert metrics.turn[1].recall_any == 0.0
    assert metrics.turn[3].recall_all == 1.0


def test_abstention_is_explicitly_skipped_from_retrieval_metrics() -> None:
    case = list(iter_longmemeval_cases(FIXTURE_PATH))[1]

    metrics = evaluate_ranked_evidence(
        case,
        RankedEvidence(turn_ids=("garden-session_1",), session_ids=("garden-session",)),
        cutoffs=(1, 5),
    )

    assert metrics.skipped is True
    assert metrics.session == {}
    assert metrics.turn == {}


def test_benchmark_lexical_ingest_keeps_sources_searchable_without_graph_work(
    tmp_path: Path,
) -> None:
    case = next(iter_longmemeval_cases(FIXTURE_PATH))
    plan = build_add_requests(case)
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()

    for request in plan:
        store.add_benchmark_lexical(request)
    service = MemoryService(store, LexicalRetrievalPipeline(store, neighbor_radius=1))
    scored = service.search_scored(
        SearchRequest(
            query=case.question,
            user_id=f"longmemeval:{case.question_id}",
            top_k=5,
        )
    )

    assert store.count_messages(user_id=f"longmemeval:{case.question_id}") == 4
    assert store.count_message_facets(user_id=f"longmemeval:{case.question_id}") == 0
    assert scored[0].message.session_id == "evidence-session"
    assert scored[0].message.content == "Riley adopted a dog named Pixel."
    assert scored[0].message.occurred_at_ms == case.sessions[1].occurred_at_ms


def test_cli_runs_real_pipeline_and_writes_truthful_artifacts(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "run_longmemeval.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data",
            str(FIXTURE_PATH),
            "--output-dir",
            str(tmp_path),
            "--cutoffs",
            "1,5",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in (tmp_path / "retrieval.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert summary["dataset"]["sha256"]
    assert summary["cases"] == {"total": 2, "evaluated": 1, "skipped_abstention": 1}
    assert summary["configuration"]["ingestion_mode"] == "benchmark-lexical"
    assert summary["configuration"]["indexed_roles"] == ["user", "assistant"]
    assert summary["configuration"]["retrieval_depth"] == 100
    assert summary["metrics"]["session"]["recall_any@5"] == 1.0
    assert records[0]["retrieved_session_ids"][0] == "evidence-session"
    assert records[0]["answer"] == "Pixel"
    assert records[0]["is_abstention"] is False
    assert records[0]["retrieved_evidence"][0]["turn_id"] == "evidence-session_1"
    assert records[0]["retrieved_evidence"][0]["request_id"].startswith(
        "longmemeval-tiny-single-user-"
    )
    assert "local retrieval evidence evaluation" in report.lower()
    assert "not an official leaderboard score" in report.lower()
    assert "both user and assistant turns" in report.lower()
    assert "## Per-question-type metrics" in report


def test_cli_can_take_a_reproducible_per_type_sample(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "run_longmemeval.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data",
            str(FIXTURE_PATH),
            "--output-dir",
            str(tmp_path),
            "--per-type-limit",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert summary["cases"] == {
        "total": 1,
        "evaluated": 1,
        "skipped_abstention": 0,
    }
    assert summary["configuration"]["per_type_limit"] == 1
    assert "Per-type limit: 1" in report
