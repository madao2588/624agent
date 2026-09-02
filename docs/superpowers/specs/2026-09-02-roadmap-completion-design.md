# 624agent Roadmap Completion Design

Date: 2026-09-02

## Goal

Turn the improvement summary into a reproducible textual-memory submission that
still returns only immutable source evidence. The evaluated Add/Search contract
stays unchanged; all new structure is an internal retrieval index with source
provenance.

## Product modes

The service has two explicit modes rather than one ambiguous collection of
optional switches:

- `local`: deterministic SQLite FTS, local structural annotations, state links,
  graph expansion, and optional user-selected demo connections. It remains free
  and works without credentials.
- `evaluation`: a frozen configuration intended for the leaderboard. It fixes
  enabled retrieval modules, candidate limits, timeouts, and model identity. The
  current Full checklist requires `gpt-4o-mini` during Add and Search, so this
  mode must fail closed when the required OpenAI credential is absent. Model
  output may enrich indexes and queries but may never replace source evidence.

DeepSeek remains a demo query-expansion provider, not a vector model and not the
formal evaluation default.

## Durable memory representation

`messages` remains the source of truth. Three auxiliary structures are added:

1. `message_facets`
   - source message, user, kind, raw value, normalized value, confidence
   - kinds cover entity, alias, place, time, event, action, preference, habit,
     rule condition, requirement, prohibition, exception, and event status
2. `memory_relations`
   - source message, target message, relation, anchor, confidence
   - relations cover shared entity/event, alias, pronoun continuation, and
     state transitions
3. `schema_metadata`
   - versioned, idempotent backfills for local deterministic annotations

Every facet and relation points back to one or more raw messages. No generated
summary is returned by Search.

## Local annotation

The local analyzer is conservative and dependency-free:

- extracts English proper-name spans and bounded Chinese named spans;
- records explicit aliases and lets both names reach the same evidence group;
- carries an unambiguous entity across adjacent messages when a pronoun is used;
- normalizes absolute and common relative dates against the source timestamp;
- classifies update, cancellation, restoration, and forget signals;
- separates preference, aversion, repeated habit, and one-off behavior;
- separates rule condition, required action, prohibition, order, and exception.

Low-confidence inference is allowed only as a retrieval hint. It is never
rendered as a fact.

## Optional evaluation enrichment

The evaluation model receives the current Add message batch during Add and the
current question/options during Search. It returns strict JSON containing only
facets, aliases, status signals, or search terms. Responses are bounded,
validated, sanitized, and merged with local annotations. Provider failure is a
503; the service must not silently change evaluated behavior.

The model never produces the final answer and model-generated text is never
stored as a source memory.

## State and governance

State chains are generalized from explicit replacement words to transitions:

- supersede/update
- cancel
- resume/restore
- forget

The newest transition is active. Default/current questions rank the active end
of a chain first and suppress stale predecessors when enough active evidence is
available. History/change questions return the complete bounded chain in source
time order. Forgotten sources remain auditable internally but are omitted from
ordinary Search.

Implicit updates are linked only when messages share a strong event/entity
anchor plus a conflicting temporal, location, or status facet.

## Retrieval

Search becomes a bounded multi-route pipeline:

1. BM25/FTS source recall.
2. Query-facet recall for entity, alias, place, time, preference, and rule
   intent.
3. Optional dense recall.
4. State/governance resolution.
5. Two- to three-hop facet graph expansion.
6. Dynamic same-session context expansion based on shared facets or lexical
   overlap.
7. Reciprocal-rank fusion, source deduplication, diversity, recency/state
   adjustment, and a relevance threshold.

At least one grounded route must support a result. No-evidence queries return an
empty array instead of filling `top_k`.

## Explainability and demo

The official Search response keeps only `id`, `content`, `score`, and
`created_at`. A separate authenticated/local diagnostics endpoint exposes:

- match reasons and route names;
- extracted facets;
- active versus historical state;
- relation edges among returned evidence.

The playground uses this endpoint to render a timeline, current/history split,
a compact relationship graph, retrieval-mode explanation, key persistence risk,
and one-click key clearing.

## Evaluation and operations

The checked-in synthetic suite covers every public capability dimension without
using private questions or labels. It reports Recall@K, MRR, nDCG, noise rate,
empty-result accuracy, and latency as local diagnostics only.

Release verification includes 64 concurrent Add calls, 256 concurrent Search
calls, `top_k=100`, restart/migration recovery, Docker cold start, user
isolation, prompt-injection memories, log redaction, and a clean-build replay.

## Compatibility boundaries

- Add/Search request and response schemas remain compatible with the official
  synchronous contract.
- `user_id` is present in every auxiliary table and every lookup predicate.
- external model and embedding failures never silently fall back in evaluation
  mode.
- no new runtime dependency is required for the local mode.
- existing databases are migrated in place with idempotent backfills.
