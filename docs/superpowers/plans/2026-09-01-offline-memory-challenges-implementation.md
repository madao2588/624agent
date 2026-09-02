# Offline Memory Challenges Implementation Plan

**Goal:** Add a model-free, evidence-first challenge runner and use its failures
to improve the deterministic retrieval path.

## Task 1: Lock the missing retrieval behaviors

**Files:** `tests/test_retrieval.py`

1. Add a test proving question stopwords alone cannot retrieve unrelated text.
2. Add a test proving a `current` query ranks the newest matching timestamp
   before an older state.
3. Add a test proving a proper-name bridge can return both sides of a
   cross-session relation.
4. Run the focused tests and confirm they fail for the intended reasons.

**Acceptance:** the new tests are red against the current implementation; no
existing assertion is weakened.

## Task 2: Implement bounded deterministic retrieval improvements

**Files:** `src/aml_memory/retrieval.py`

1. Add content-term filtering while keeping untrusted FTS text safely quoted.
2. Detect explicit current-state intent and reorder only the direct lexical
   candidate list by source time.
3. Extract a capped set of likely proper-name bridge terms from the strongest
   direct results and perform one same-user FTS lookup.
4. Merge bridge candidates below direct candidates before existing same-session
   neighbor expansion.
5. Run the focused tests after each minimal behavior change.

**Acceptance:** new and existing retrieval tests pass; bridge lookup is bounded,
non-recursive, stable, and user-isolated.

## Task 3: Add the readable challenge corpus and runner

**Files:** `evaluation/memory_challenges.json`,
`scripts/run_memory_challenges.py`, `tests/test_memory_challenges.py`,
`README.md`

1. Check in English-first multi-session cases plus one Chinese case.
2. Add a runner that creates a temporary database, calls the real service
   components, and prints expected and returned raw evidence.
3. Add tests for corpus validation and runner exit behavior.
4. Document the single local command and explain that the output is not an
   official score.

**Acceptance:** the runner exits zero only when every required excerpt is
visible and every no-evidence case returns an empty list; it prints no numeric
aggregate score.

## Task 4: Verify the repository

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe scripts\run_memory_challenges.py
```

**Acceptance:** every command exits zero and the final challenge output contains
readable evidence for every case, with no official-score claim.
