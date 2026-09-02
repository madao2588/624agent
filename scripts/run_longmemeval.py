"""Run local LongMemEval-S evidence retrieval through the real memory service."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Literal, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from aml_memory.benchmarks.longmemeval import (  # noqa: E402
    CaseRetrievalMetrics,
    LongMemEvalCase,
    RetrievalAtK,
    build_ingestion_plan,
    evaluate_ranked_evidence,
    iter_longmemeval_cases,
    rank_scored_messages,
)
from aml_memory.retrieval import LexicalRetrievalPipeline  # noqa: E402
from aml_memory.schemas import SearchRequest  # noqa: E402
from aml_memory.service import MemoryService  # noqa: E402
from aml_memory.store import MemoryStore  # noqa: E402

RETRIEVAL_DEPTH = 100


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_record(metric: RetrievalAtK) -> dict[str, float]:
    return {
        "recall_any": metric.recall_any,
        "recall_all": metric.recall_all,
        "ndcg": metric.ndcg,
    }


def _case_metric_record(metrics: CaseRetrievalMetrics) -> dict[str, object]:
    return {
        "skipped": metrics.skipped,
        "session": {
            str(k): _metric_record(metric) for k, metric in metrics.session.items()
        },
        "turn": {
            str(k): _metric_record(metric) for k, metric in metrics.turn.items()
        },
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _aggregate(
    metrics: Sequence[CaseRetrievalMetrics], cutoffs: Sequence[int]
) -> dict[str, dict[str, float]]:
    evaluated = [metric for metric in metrics if not metric.skipped]
    result: dict[str, dict[str, float]] = {"session": {}, "turn": {}}
    for granularity in ("session", "turn"):
        output = result[granularity]
        for k in cutoffs:
            at_k = [getattr(metric, granularity)[k] for metric in evaluated]
            output[f"recall_any@{k}"] = _mean([item.recall_any for item in at_k])
            output[f"recall_all@{k}"] = _mean([item.recall_all for item in at_k])
            output[f"ndcg@{k}"] = _mean([item.ndcg for item in at_k])
    return result


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _render_report(summary: Mapping[str, object], cutoffs: Sequence[int]) -> str:
    cases = summary["cases"]
    assert isinstance(cases, dict)
    metrics = summary["metrics"]
    assert isinstance(metrics, dict)
    configuration = summary["configuration"]
    assert isinstance(configuration, dict)
    question_ids = configuration["question_ids"]
    question_types = configuration["question_types"]
    assert isinstance(question_ids, list)
    assert isinstance(question_types, list)
    limit = configuration["limit"]
    per_type_limit = configuration["per_type_limit"]
    lines = [
        "# LongMemEval-S local retrieval evidence evaluation",
        "",
        "> This is not an official leaderboard score. It measures labelled source",
        "> retrieval only; no answer reader or LLM judge was run.",
        "",
        "## Run",
        "",
        f"- Cases processed: {cases['total']}",
        f"- Retrieval cases evaluated: {cases['evaluated']}",
        f"- Abstention cases skipped: {cases['skipped_abstention']}",
        f"- Ingestion mode: `{configuration['ingestion_mode']}`",
        "- Indexed source roles: both user and assistant turns",
        f"- Retrieval depth: {configuration['retrieval_depth']} turns",
        f"- Global limit: {'none' if limit is None else limit}",
        f"- Per-type limit: {'none' if per_type_limit is None else per_type_limit}",
        f"- Question ID filter: {', '.join(map(str, question_ids)) or 'all'}",
        f"- Question type filter: {', '.join(map(str, question_types)) or 'all'}",
        f"- Dataset SHA-256: `{summary['dataset_sha256']}`",
        "",
        "## Overall metrics",
        "",
        "| Granularity | Cutoff | Recall any | Recall all | nDCG |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for granularity in ("session", "turn"):
        values = metrics[granularity]
        assert isinstance(values, dict)
        for k in cutoffs:
            lines.append(
                f"| {granularity} | {k} | "
                f"{_percent(float(values[f'recall_any@{k}']))} | "
                f"{_percent(float(values[f'recall_all@{k}']))} | "
                f"{_percent(float(values[f'ndcg@{k}']))} |"
            )
    lines.extend(
        [
            "",
            "## Per-question-type metrics",
            "",
            "| Question type | Granularity | Cutoff | Recall any | Recall all | nDCG |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    by_type = summary["metrics_by_question_type"]
    assert isinstance(by_type, dict)
    for question_type, type_metrics in by_type.items():
        assert isinstance(type_metrics, dict)
        for granularity in ("session", "turn"):
            values = type_metrics[granularity]
            assert isinstance(values, dict)
            for k in cutoffs:
                lines.append(
                    f"| {question_type} | {granularity} | {k} | "
                    f"{_percent(float(values[f'recall_any@{k}']))} | "
                    f"{_percent(float(values[f'recall_all@{k}']))} | "
                    f"{_percent(float(values[f'ndcg@{k}']))} |"
                )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "`recall_any` asks whether at least one labelled source was found;",
            "`recall_all` requires every labelled source. Session rankings keep only",
            "the first hit for each session. Turn rankings use the official",
            "`has_answer` labels. LongMemEval abstention questions have no evidence",
            "location and are excluded from these retrieval aggregates.",
            "",
        ]
    )
    return "\n".join(lines)


def _selected_cases(
    cases: Iterable[LongMemEvalCase],
    *,
    question_ids: set[str],
    question_types: set[str],
    limit: int | None,
    per_type_limit: int | None,
) -> Iterable[LongMemEvalCase]:
    selected = 0
    selected_by_type: dict[str, int] = defaultdict(int)
    for case in cases:
        if question_ids and case.question_id not in question_ids:
            continue
        if question_types and case.question_type not in question_types:
            continue
        if (
            per_type_limit is not None
            and selected_by_type[case.question_type] >= per_type_limit
        ):
            continue
        if limit is not None and selected >= limit:
            return
        selected += 1
        selected_by_type[case.question_type] += 1
        yield case


def run_evaluation(
    data_path: Path,
    output_dir: Path,
    *,
    cutoffs: Sequence[int],
    question_ids: set[str] | None = None,
    question_types: set[str] | None = None,
    limit: int | None = None,
    per_type_limit: int | None = None,
    ingestion_mode: Literal["benchmark-lexical", "full"] = "benchmark-lexical",
    progress: TextIO = sys.stdout,
) -> dict[str, object]:
    normalized_cutoffs = tuple(sorted(set(cutoffs)))
    if not normalized_cutoffs or normalized_cutoffs[0] < 1 or normalized_cutoffs[-1] > 100:
        raise ValueError("cutoffs must be integers from 1 to 100")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if per_type_limit is not None and per_type_limit < 1:
        raise ValueError("per_type_limit must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_sha256 = _sha256(data_path)
    all_metrics: list[CaseRetrievalMetrics] = []
    metrics_by_type: dict[str, list[CaseRetrievalMetrics]] = defaultdict(list)
    latencies: list[float] = []
    total = 0
    evaluated = 0
    skipped = 0

    retrieval_path = output_dir / "retrieval.jsonl"
    with retrieval_path.open("w", encoding="utf-8", newline="\n") as records:
        selected_cases = _selected_cases(
            iter_longmemeval_cases(data_path),
            question_ids=question_ids or set(),
            question_types=question_types or set(),
            limit=limit,
            per_type_limit=per_type_limit,
        )
        for case in selected_cases:
            total += 1
            plan = build_ingestion_plan(case)
            with TemporaryDirectory(prefix="aml-longmemeval-") as temporary_directory:
                store = MemoryStore(Path(temporary_directory) / "memory.db")
                store.initialize()
                service = MemoryService(
                    store,
                    LexicalRetrievalPipeline(store, neighbor_radius=1),
                )
                for request in plan.requests:
                    if ingestion_mode == "benchmark-lexical":
                        store.add_benchmark_lexical(request)
                    else:
                        service.add(request)
                started_at = perf_counter()
                scored = service.search_scored(
                    SearchRequest(
                        query=case.question,
                        user_id=f"longmemeval:{case.question_id}",
                        top_k=RETRIEVAL_DEPTH,
                    )
                )
                latency_ms = (perf_counter() - started_at) * 1000

            ranked = rank_scored_messages(plan, scored)
            source_turn_by_identity = {
                (binding.request_id, binding.ordinal): binding.turn_id
                for binding in plan.source_bindings
            }
            case_metrics = evaluate_ranked_evidence(
                case,
                ranked,
                cutoffs=normalized_cutoffs,
            )
            all_metrics.append(case_metrics)
            metrics_by_type[case.question_type].append(case_metrics)
            latencies.append(latency_ms)
            if case_metrics.skipped:
                skipped += 1
            else:
                evaluated += 1
            record = {
                "question_id": case.question_id,
                "question_type": case.question_type,
                "question": case.question,
                "answer": case.answer,
                "is_abstention": case.is_abstention,
                "question_date": case.question_date,
                "answer_session_ids": list(case.answer_session_ids),
                "answer_turn_ids": list(case.answer_turn_ids),
                "retrieved_session_ids": list(ranked.session_ids),
                "retrieved_turn_ids": list(ranked.turn_ids),
                "retrieved_evidence": [
                    {
                        "turn_id": source_turn_by_identity[
                            (result.message.request_id, result.message.ordinal)
                        ],
                        "request_id": result.message.request_id,
                        "ordinal": result.message.ordinal,
                        "session_id": result.message.session_id,
                        "role": result.message.role,
                        "content": result.message.content,
                        "score": result.score,
                    }
                    for result in scored
                ],
                "latency_ms": latency_ms,
                "metrics": _case_metric_record(case_metrics),
            }
            records.write(json.dumps(record, ensure_ascii=False) + "\n")
            records.flush()
            status = "SKIP abstention" if case_metrics.skipped else "evaluated"
            print(f"[{total}] {case.question_id}: {status}", file=progress, flush=True)

    if total == 0:
        raise ValueError("no LongMemEval cases matched the requested filters")
    overall = _aggregate(all_metrics, normalized_cutoffs)
    per_type = {
        question_type: _aggregate(type_metrics, normalized_cutoffs)
        for question_type, type_metrics in sorted(metrics_by_type.items())
        if any(not metric.skipped for metric in type_metrics)
    }
    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    summary: dict[str, object] = {
        "evaluation": "LongMemEval-S local retrieval evidence evaluation",
        "official_leaderboard_score": False,
        "dataset": {
            "filename": data_path.name,
            "bytes": data_path.stat().st_size,
            "sha256": dataset_sha256,
        },
        "dataset_sha256": dataset_sha256,
        "configuration": {
            "cutoffs": list(normalized_cutoffs),
            "limit": limit,
            "per_type_limit": per_type_limit,
            "question_ids": sorted(question_ids or set()),
            "question_types": sorted(question_types or set()),
            "ingestion_mode": ingestion_mode,
            "indexed_roles": ["user", "assistant"],
            "retrieval_depth": RETRIEVAL_DEPTH,
            "reader_model": None,
            "judge_model": None,
        },
        "cases": {
            "total": total,
            "evaluated": evaluated,
            "skipped_abstention": skipped,
        },
        "metrics": overall,
        "metrics_by_question_type": per_type,
        "latency_ms": {
            "mean": _mean(latencies),
            "p95": sorted_latencies[p95_index] if sorted_latencies else 0.0,
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        _render_report(summary, normalized_cutoffs),
        encoding="utf-8",
    )
    return summary


def _parse_cutoffs(value: str) -> tuple[int, ...]:
    try:
        cutoffs = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("cutoffs must be comma-separated integers") from error
    if not cutoffs or min(cutoffs) < 1 or max(cutoffs) > 100:
        raise argparse.ArgumentTypeError("cutoffs must be integers from 1 to 100")
    return cutoffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "longmemeval" / "latest",
    )
    parser.add_argument("--cutoffs", type=_parse_cutoffs, default=(1, 5, 10))
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--per-type-limit",
        type=int,
        help="Select at most this many instances from each question type.",
    )
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--question-type", action="append", default=[])
    parser.add_argument(
        "--ingestion-mode",
        choices=("benchmark-lexical", "full"),
        default="benchmark-lexical",
        help="Use fast raw-source indexing or the complete structured Add path.",
    )
    args = parser.parse_args()
    run_evaluation(
        args.data,
        args.output_dir,
        cutoffs=args.cutoffs,
        question_ids=set(args.question_id),
        question_types=set(args.question_type),
        limit=args.limit,
        per_type_limit=args.per_type_limit,
        ingestion_mode=args.ingestion_mode,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
