# Explicit State Chain Implementation Plan

## Task 1: Lock the state relation contract

**Files:** `tests/test_store.py`, `tests/test_retrieval.py`

1. Add a store test for an explicit reschedule relation across two Add calls.
2. Reopen the database and prove both source messages remain connected.
3. Prove a different user and a weak one-word overlap are not connected.
4. Add lexical and hybrid retrieval tests where only the old fact matches the
   query but the linked replacement must rank first.
5. Run focused tests and confirm the intended failures.

**Acceptance:** tests fail because state storage and expansion do not yet exist,
not because of malformed fixtures.

## Task 2: Add deterministic linking and atomic persistence

**Files:** `src/aml_memory/state.py`, `src/aml_memory/store.py`,
`src/aml_memory/models.py`

1. Implement explicit update-signal detection and topic-term normalization.
2. Add the `state_relations` migration and indexes.
3. During Add, retrieve bounded same-user FTS candidates and select one prior
   state using deterministic overlap and time rules.
4. Insert the source, FTS row, optional vector, and relation in the same
   transaction.
5. Add a bounded bidirectional chain reader that applies `user_id` in relation
   lookup and source-row lookup.

**Acceptance:** store tests pass after restart and no relation crosses users.

## Task 3: Expand current-state retrieval

**Files:** `src/aml_memory/ports.py`, `src/aml_memory/retrieval.py`

1. Add the chain reader to the retrieval store protocol.
2. Expand chains only for explicit current-state intent.
3. Put the newest source first while retaining the history sources.
4. Apply the same behavior to lexical and hybrid pipelines.

**Acceptance:** focused lexical and hybrid tests pass without changing the HTTP
response shape.

## Task 4: Make the behavior visible and verify

**Files:** `evaluation/memory_challenges.json`, `README.md`

1. Strengthen the temporal challenge so the new message does not contain the
   query's key old term.
2. Document explicit state links and their conservative limits.
3. Run Ruff, Mypy, all tests, Compileall, diff checks, and the readable
   challenge runner with stop-on-first-failure semantics.

**Acceptance:** every command exits zero and the temporal challenge visibly
returns the replacement before its predecessor.
