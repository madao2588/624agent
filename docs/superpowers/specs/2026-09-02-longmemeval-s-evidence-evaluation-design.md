# LongMemEval-S Evidence Evaluation Design

**Status:** approved by the user's request to continue the recommended
LongMemEval-S work on 2026-09-02

## Goal

Replace the impression created by the twenty hand-written challenge cases with
a reproducible evaluation path over the official cleaned LongMemEval-S schema.
The first deliverable measures whether the real Add/Search pipeline retrieves
the labelled source sessions and turns. It does not claim an official
leaderboard or end-to-end question-answering score.

Official references:

- https://github.com/xiaowu0162/LongMemEval
- https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned

## Chosen scope

Implement a dependency-free dataset adapter and retrieval evaluator that:

1. streams the 277 MB JSON array instead of loading it all into memory;
2. validates the parallel session ids, dates, and session arrays;
3. preserves every non-blank original turn, role, source ordinal, session id,
   and session timestamp;
4. ingests one benchmark question into an isolated temporary memory store;
5. searches both user and assistant turns through `MemoryService.search_scored`
   at the contract depth of 100, the same retrieval path used by the API;
6. maps returned stored messages back to official session- and turn-level
   evidence labels;
7. reports official-style `recall_any`, `recall_all`, and nDCG at configurable
   cutoffs, with abstention questions excluded from retrieval aggregates; and
8. writes reproducible JSONL evidence plus JSON and Markdown summaries that
   include the dataset hash and run configuration.

The checked-in tests use a tiny official-shaped fixture. The real 277 MB corpus
stays under ignored `artifacts/` storage and is never committed.

## Why this slice comes first

Three implementation paths were considered:

- **Evidence retrieval first (chosen):** free, deterministic, directly tests
  the memory system, and produces inspectable failures.
- **Full reader and LLM judge:** closer to the final benchmark, but needs paid
  model calls and would mix retrieval quality with reader and judge quality.
- **Leaderboard-only submission:** authoritative but blocked until a benchmark
  API key is issued and offers poor local debugging feedback.

The chosen path creates the foundation for the other two without inventing a
score.

## Data model

Each instance contains `question_id`, `question_type`, `question`, `answer`,
`question_date`, parallel `haystack_session_ids`, `haystack_dates`, and
`haystack_sessions`, plus `answer_session_ids`. Turns may contain
`has_answer: true`.

The adapter creates stable turn identities as
`<session_id>_<one-based-turn-number>`. A retrieved `StoredMessage` maps back
through its original `session_id` and `ordinal`. Session rankings deduplicate
turn hits while preserving the first-hit order.

## Ingestion and isolation

Every question receives a deterministic, isolated user id. A fresh temporary
SQLite database is used for each question so histories cannot leak between
instances and the full run does not retain hundreds of millions of tokens in
one database.

Sessions are split only when they exceed the platform-safe ingestion envelope
of twenty messages or roughly two thousand whitespace-delimited words. Chunks
keep the original session id and get stable request ids, so session-level
labels remain valid.

## Metrics

For every non-abstention instance and cutoff `k`:

- `recall_any@k`: at least one labelled item appears in the top k;
- `recall_all@k`: every labelled item appears in the top k;
- `ndcg@k`: binary-relevance normalized discounted cumulative gain.

Session metrics operate on unique retrieved session ids. Turn metrics operate
on individual retrieved turns labelled by `has_answer`. Aggregates are macro
means overall and by `question_type`. Questions whose id ends in `_abs` are
listed as skipped for retrieval metrics, matching the official benchmark
convention.

## Outputs and truthfulness boundary

The runner writes:

- `retrieval.jsonl`: expected answer, ranked source ids, traceable raw evidence,
  and per-case metrics;
- `summary.json`: machine-readable aggregate metrics and provenance;
- `report.md`: a readable overall and per-type report.

Every output labels itself as local retrieval evidence evaluation. It must not
use the words "official score" except to say that it is not one. A later reader
adapter may consume `retrieval.jsonl` to generate hypotheses for the upstream
LongMemEval judge.

## Failure handling

Malformed schemas fail with the exact instance and field name. Invalid dates
fail instead of silently replacing them with the current time. Output files are
written incrementally so an interrupted long run retains completed case
evidence. A nonzero exit code indicates invalid data or a runtime failure, not
a low retrieval score.
