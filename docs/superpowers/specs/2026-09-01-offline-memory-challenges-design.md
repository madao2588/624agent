# Offline Memory Challenges Design

**Status:** approved in chat on 2026-09-01

## Goal

Make memory quality visible without an official leaderboard key, an embedding
service, or a generated answer. The challenge runner will add realistic
multi-session conversations, ask benchmark-shaped questions, and show the raw
evidence returned by the same retrieval pipeline used by the API.

## Scope

The first challenge set is primarily English, matching the public textual
memory benchmarks, with one Chinese compatibility case. It covers:

- explicit facts;
- option-assisted paraphrases;
- current-state updates;
- evidence connected across sessions;
- preferences;
- procedures;
- absence of evidence; and
- Chinese exact-term retrieval.

Each case names the exact source excerpts that must be visible. The runner
prints questions, expected excerpts, returned evidence, and `FOUND`/`MISSING`
labels. It deliberately does not calculate a leaderboard-style score.

## Retrieval changes driven by the cases

The default no-model path remains deterministic and dependency-free. Three
bounded improvements are allowed:

1. **Content-term queries.** Remove a small fixed set of English question words
   before building the FTS disjunction. This prevents an unrelated message
   containing only words such as `the` or `is` from becoming evidence.
2. **Current-state ordering.** When a query explicitly asks for the current,
   latest, or most recent state, order matching lexical candidates by their
   source timestamp before normal stable tie-breaking.
3. **Entity bridge expansion.** Extract a bounded set of likely proper names
   from the strongest direct lexical hits, look them up within the same user,
   and add those source messages at a lower score. This supplies the missing
   relation side of simple two-message, cross-session questions without an
   unbounded agent loop or a generated fact.

All paths continue to return immutable source messages, enforce `user_id` in
every lookup, and honor `top_k`. Entity expansion is limited to one additional
lookup and never recursively expands its own results.

## Non-goals

- No embedding or cloud model integration.
- No generated final answers.
- No benchmark answer or label leakage.
- No broad knowledge graph or heuristic fact extraction.
- No numeric claim about official leaderboard quality.

## Acceptance criteria

- Regression tests demonstrate the three missing behaviors before the code is
  changed and pass afterwards.
- The checked-in challenge set can be run with one local command.
- Output makes every expected and returned source excerpt readable.
- Existing API, isolation, idempotency, hybrid retrieval, and preflight tests
  continue to pass.
