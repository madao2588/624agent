from math import isclose

from aml_memory.metrics import RetrievalObservation, calculate_metrics


def test_calculates_retrieval_quality_noise_abstention_and_latency() -> None:
    metrics = calculate_metrics(
        [
            RetrievalObservation(
                required_excerpts=("alpha", "beta"),
                returned_contents=("alpha evidence", "noise", "beta evidence"),
                expect_empty=False,
                latency_ms=10.0,
            ),
            RetrievalObservation(
                required_excerpts=(),
                returned_contents=(),
                expect_empty=True,
                latency_ms=20.0,
            ),
        ]
    )

    assert metrics.case_count == 2
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr == 1.0
    assert isclose(metrics.ndcg, 1.5 / (1.0 + 1.0 / 1.584962500721156))
    assert isclose(metrics.noise_rate, 1.0 / 3.0)
    assert metrics.abstention_accuracy == 1.0
    assert metrics.mean_latency_ms == 15.0
    assert metrics.p95_latency_ms == 20.0


def test_empty_observation_list_returns_zeroed_diagnostics() -> None:
    metrics = calculate_metrics([])

    assert metrics.case_count == 0
    assert metrics.recall_at_k == 0.0
    assert metrics.abstention_accuracy == 0.0
