# 624agent Roadmap Completion Implementation Plan

Date: 2026-09-02

This plan implements the approved
[`agent-memory-improvement-summary.md`](../../agent-memory-improvement-summary.md)
in test-driven, reversible batches.

## 1. Freeze the baseline and evaluation profile

Files:

- `src/aml_memory/config.py`
- `src/aml_memory/app.py`
- `evaluation/evaluation-profile.json`
- `tests/test_config.py`

Steps:

1. Add failing tests for explicit `local` and `evaluation` modes.
2. Require the frozen model/config only in evaluation mode.
3. Add a checked-in machine-readable profile and startup validation.

Acceptance: local starts without credentials; evaluation fails closed when its
required model credential or fixed model is missing.

## 2. Add source-backed facets and temporal normalization

Files:

- `src/aml_memory/analysis.py` (new)
- `src/aml_memory/models.py`
- `src/aml_memory/store.py`
- `src/aml_memory/ports.py`
- `tests/test_analysis.py` (new)
- `tests/test_store.py`

Steps:

1. Write failing unit tests for entities, aliases, pronouns, places, absolute and
   relative time, event status, preferences/habits, and rule parts.
2. Add immutable annotation models and a conservative local analyzer.
3. Add `message_facets` and `memory_relations` schemas and indexes.
4. Persist annotations in the Add transaction and add idempotent backfill.
5. Add user-isolation and migration tests.

Acceptance: every auxiliary row is user-scoped, source-backed, idempotent, and
survives restart.

## 3. Generalize state and memory governance

Files:

- `src/aml_memory/state.py`
- `src/aml_memory/store.py`
- `src/aml_memory/ports.py`
- `src/aml_memory/retrieval.py`
- `tests/test_store.py`
- `tests/test_retrieval.py`

Steps:

1. Add failing cases for implicit update, cancel, restore, forget, current, and
   history queries.
2. Link transitions only with strong shared anchors.
3. Expose active/history chain lookups from the store.
4. Make current/default retrieval prefer active evidence; history retrieval
   expands the auditable chain; ordinary retrieval omits forgotten sources.

Acceptance: state ordering remains deterministic across restart and never
crosses users.

## 4. Add multi-hop, personalized, and rule-aware retrieval

Files:

- `src/aml_memory/retrieval.py`
- `src/aml_memory/store.py`
- `src/aml_memory/ports.py`
- `tests/test_retrieval.py`

Steps:

1. Add failing 2-hop and 3-hop provenance cases.
2. Add preference reversal, habit-versus-one-off, conditional rule, prohibition,
   ordering, and exception cases.
3. Add bounded facet recall and graph traversal.
4. Scope preference/rule expansion to matching facets instead of returning every
   tagged message.

Acceptance: every expanded result has a source-backed path of at most three
hops and unrelated preference/rule memories stay out.

## 5. Replace fixed neighbor expansion with grounded reranking

Files:

- `src/aml_memory/models.py`
- `src/aml_memory/retrieval.py`
- `src/aml_memory/config.py`
- `tests/test_retrieval.py`

Steps:

1. Add failing noise, diversity, dynamic context, and low-similarity dense cases.
2. Track internal route/reason metadata without changing official evidence.
3. Fuse lexical, facet, graph, state, tag, and optional dense ranks.
4. Add relevance and dense-similarity thresholds plus deterministic tie breaks.

Acceptance: unsupported queries are empty and useful context can outrank an
unrelated direct token hit.

## 6. Add evaluation enrichment with gpt-4o-mini

Files:

- `src/aml_memory/enrichment.py` (new)
- `src/aml_memory/query_expansion.py`
- `src/aml_memory/service.py`
- `src/aml_memory/app.py`
- `src/aml_memory/config.py`
- `tests/test_enrichment.py` (new)
- `tests/test_api_add_search.py`

Steps:

1. Add provider-contract tests with fake HTTP responses.
2. Validate bounded JSON annotations/search terms.
3. Invoke enrichment on Add and query planning on Search only in evaluation mode.
4. Preserve idempotency-before-provider-call and fail closed with sanitized 503.

Acceptance: the frozen evaluation path uses the required model on both Add and
Search while Search still returns only original source messages.

## 7. Expand the legal synthetic benchmark and metrics

Files:

- `evaluation/memory_challenges.json`
- `scripts/run_memory_challenges.py`
- `src/aml_memory/metrics.py` (new)
- `tests/test_memory_challenges.py`

Steps:

1. Add all public capability scenarios and explicit expected source IDs/order.
2. Compute Recall@K, MRR, nDCG, noise, abstention accuracy, and latency.
3. Print them as local diagnostics with a non-official disclaimer.
4. Add per-module ablation switches in the evaluation profile.

Acceptance: the suite is deterministic, contains no private evaluation content,
and fails when any required evidence/order/empty result regresses.

## 8. Strengthen capacity, recovery, security, and CI

Files:

- `src/aml_memory/preflight.py`
- `tests/test_concurrency.py`
- `tests/test_restart_recovery.py`
- `tests/test_logging_safety.py`
- `.github/workflows/ci.yml`
- `Dockerfile`

Steps:

1. Verify Add 64, Search 256, Top K 100.
2. Add migration, restart, prompt-injection-memory, and secret/body redaction
   regressions.
3. Run maximum preflight against the built container in CI.
4. Add a health readiness check for database and required indexes.

Acceptance: a clean container build passes the maximum black-box preflight and
restarts with intact, isolated data.

## 9. Add explainability diagnostics and finish the playground

Files:

- `src/aml_memory/schemas.py`
- `src/aml_memory/app.py`
- `src/aml_memory/demo.html`
- `tests/test_demo.py`
- `tests/test_api_add_search.py`

Steps:

1. Add a non-leaderboard diagnostics endpoint behind the same authentication.
2. Return routes/reasons, facets, state labels, and bounded relation edges.
3. Render a memory timeline, active/history columns, relationship graph, and
   per-evidence match reason.
4. Keep local/DeepSeek/embedding/evaluation modes visibly distinct; retain key
   risk messaging and clear-key action.

Acceptance: the official endpoint is unchanged and browser QA shows the new
views with real API data.

## 10. Reproducibility and release

Files:

- `README.md`
- `evaluation/SUBMISSION.md`
- `.gitignore`
- release metadata

Steps:

1. Align documentation with the exact final behavior and official current
   checklist.
2. Run Ruff, Mypy, compileall, full Pytest, synthetic benchmark, maximum
   preflight, Docker cold-build smoke, and log/secret scans.
3. Run GitNexus `detect_changes` and review all affected flows.
4. Create Lore-protocol commits, push `main`, record the immutable commit SHA,
   and create the release tag.

Acceptance: a clean checkout reproduces the verified service and all submission
fields except private human contact data are complete.
