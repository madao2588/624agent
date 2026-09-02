# LongMemEval-S Evidence Evaluation Implementation Plan

## Task 1: Lock the official-shaped contract with tests

**Files:** `tests/fixtures/longmemeval_tiny.json`,
`tests/test_longmemeval.py`

1. Add one answerable and one abstention instance using the official field
   layout.
2. Test streaming, schema validation, date conversion, stable Add requests,
   evidence identity mapping, and official-style metrics.
3. Test a complete tiny run and assert the JSONL, JSON, and Markdown provenance
   boundaries.
4. Run the focused tests and observe the expected import failure.

**Acceptance:** the tests fail because the adapter does not exist yet, not
because the fixture is malformed.

## Task 2: Implement the dataset and metric core

**Files:** `src/aml_memory/benchmarks/__init__.py`,
`src/aml_memory/benchmarks/longmemeval.py`

1. Add a constant-memory JSON-array iterator and strict field parsers.
2. Parse official session dates without depending on the machine locale.
3. Build platform-safe Add requests while preserving source identity.
4. Map scored stored messages to turn and session ids.
5. Calculate per-case and aggregate session/turn metrics.
6. Run focused tests until green, then refactor only duplicated parsing logic.

**Acceptance:** all pure adapter and metric tests pass without new packages.

## Task 3: Add the real-pipeline runner and artifacts

**Files:** `scripts/run_longmemeval.py`, `tests/test_longmemeval.py`

1. Run each selected instance in an isolated temporary store through
   `MemoryService` and `LexicalRetrievalPipeline`.
2. Add CLI filters for limit, question id/type, cutoffs, and output directory.
3. Write incremental retrieval JSONL and final JSON/Markdown summaries.
4. Verify the tiny fixture through the command line.

**Acceptance:** the tiny run exits zero, returns labelled source evidence for
the answerable case, skips the abstention case in retrieval aggregates, and
produces all three artifact files.

## Task 4: Document and exercise the public corpus path

**Files:** `README.md`, `docs/624agent-current-project-summary.md`

1. Document the official download URL and smoke/full commands.
2. Explicitly distinguish the twenty synthetic diagnostics from LongMemEval-S.
3. Download the official cleaned S corpus under ignored `artifacts/` storage.
4. Run a bounded real-data smoke sample and then all 500 records; record the
   observed evidence metrics without calling them an official result.

**Acceptance:** a new contributor can reproduce the adapter test, stratified
smoke run, and full run, and the summary states exactly what has and has not
been measured.

## Task 5: Verify and publish

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src scripts
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe scripts\scan_secrets.py
node .gitnexus/run.cjs detect-changes --base main
```

Then stage only the named project files, create a Lore-format commit, push to
the existing origin, and verify the GitHub workflow.

**Acceptance:** every local gate passes, GitNexus shows only the expected new
benchmark surface and documentation changes, and remote CI is green.
