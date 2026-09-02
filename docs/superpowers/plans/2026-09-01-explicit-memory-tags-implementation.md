# Explicit Memory Tags Implementation Plan

## Task 1: Prove the lexical gap

**Files:** `evaluation/memory_challenges.json`, `tests/test_retrieval.py`,
`tests/test_store.py`

1. Rewrite the preference and procedure challenges so their questions do not
   share useful words with the required evidence.
2. Add store tests for tag persistence, idempotency, and user isolation.
3. Add lexical and hybrid retrieval tests for intent-only recall.
4. Run focused tests and capture the expected failures.

## Task 2: Persist explicit source tags atomically

**Files:** `src/aml_memory/tags.py`, `src/aml_memory/store.py`

1. Implement deterministic source and query classifiers.
2. Add the `message_tags` table and indexes.
3. Write tags inside the existing Add transaction.
4. Add bounded same-user tag reads and test helpers.

## Task 3: Add intent-aware retrieval

**Files:** `src/aml_memory/ports.py`, `src/aml_memory/retrieval.py`

1. Extend the retrieval store protocol with tagged-source lookup.
2. Fuse detected tag channels below direct evidence.
3. Apply the same helper to lexical and hybrid pipelines.
4. Preserve stable order, raw evidence, and `top_k`.

## Task 4: Verify and audit

**Files:** `README.md`

1. Document what is and is not inferred.
2. Run Ruff, Mypy, all tests, Compileall, readable challenges, and diff checks
   with stop-on-first-failure behavior.
3. Review repository status and report remaining semantic limitations without
   claiming an official benchmark result.
