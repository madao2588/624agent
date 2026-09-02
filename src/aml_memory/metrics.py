"""Deterministic local diagnostics for source-evidence retrieval."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalObservation:
    required_excerpts: tuple[str, ...]
    returned_contents: tuple[str, ...]
    expect_empty: bool
    latency_ms: float


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    case_count: int
    recall_at_k: float
    mrr: float
    ndcg: float
    noise_rate: float
    abstention_accuracy: float
    mean_latency_ms: float
    p95_latency_ms: float


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _discounted_gain(relevances: list[int]) -> float:
    return sum(
        relevance / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


def calculate_metrics(observations: list[RetrievalObservation]) -> RetrievalMetrics:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    abstentions: list[float] = []
    latencies = [observation.latency_ms for observation in observations]
    irrelevant_count = 0
    returned_count = 0

    for observation in observations:
        relevant_flags = [
            int(
                any(
                    excerpt in content
                    for excerpt in observation.required_excerpts
                )
            )
            for content in observation.returned_contents
        ]
        returned_count += len(relevant_flags)
        irrelevant_count += len(relevant_flags) - sum(relevant_flags)

        if observation.required_excerpts:
            found = sum(
                any(excerpt in content for content in observation.returned_contents)
                for excerpt in observation.required_excerpts
            )
            recalls.append(found / len(observation.required_excerpts))
            first_relevant = next(
                (rank for rank, relevant in enumerate(relevant_flags, start=1) if relevant),
                None,
            )
            reciprocal_ranks.append(
                1.0 / first_relevant if first_relevant is not None else 0.0
            )
            ideal_count = min(
                len(observation.required_excerpts),
                len(observation.returned_contents),
            )
            ideal_gain = _discounted_gain([1] * ideal_count)
            ndcgs.append(
                _discounted_gain(relevant_flags) / ideal_gain if ideal_gain else 0.0
            )

        if observation.expect_empty:
            abstentions.append(float(not observation.returned_contents))

    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(len(sorted_latencies) * 0.95) - 1)
    p95 = sorted_latencies[p95_index] if sorted_latencies else 0.0
    return RetrievalMetrics(
        case_count=len(observations),
        recall_at_k=_mean(recalls),
        mrr=_mean(reciprocal_ranks),
        ndcg=_mean(ndcgs),
        noise_rate=(irrelevant_count / returned_count if returned_count else 0.0),
        abstention_accuracy=_mean(abstentions),
        mean_latency_ms=_mean(latencies),
        p95_latency_ms=p95,
    )
