# Memory Playground Implementation Plan

**Goal:** Add a local browser experience that demonstrates real Add/Search
memory behavior without changing the evaluation contract.

**Architecture:** FastAPI serves one packaged, self-contained HTML page. The
page calls the existing same-origin Add/Search endpoints and keeps only visual
activity state in the browser. Memory persistence, retrieval, ordering, and
user isolation remain backend responsibilities.

**Constraints:** No new dependency, no scoring, no delete/reset API, no final
answer generation, no bypass of API authentication, and no change to the
official request/response schemas.

---

## Task 1: Lock the demo route contract

**Files:**
- Add: `tests/test_demo.py`
- Modify: `src/aml_memory/app.py`

1. Write tests requiring `GET /demo` to return public HTML with no-store
   caching, required accessible controls, and no OpenAPI entry.
2. Run `pytest tests/test_demo.py -q` and observe the expected 404 failure.
3. Add the smallest route implementation needed to serve a packaged HTML file.
4. Rerun the focused test and make it pass.

## Task 2: Build the guided experience

**Files:**
- Add: `src/aml_memory/demo.html`
- Modify: `tests/test_demo.py`

1. Extend the test contract for the identity switcher, prepared-story action,
   custom-memory form, query form, results region, live status, and fresh-start
   action.
2. Observe the focused test fail for the missing controls.
3. Implement semantic HTML, token-based responsive CSS, and dependency-free
   JavaScript that calls the real Add/Search routes.
4. Render all user-controlled values with DOM text APIs and show request
   loading/success/error states.
5. Rerun the focused test until green, then run the complete unit suite.

## Task 3: Document and package the page

**Files:**
- Modify: `README.md`
- Verify: built wheel and Docker image

1. Add concise `/demo` startup and usage instructions.
2. Build a wheel and verify it contains `aml_memory/demo.html`.
3. Build the Docker image, start it, and verify `/demo` plus the existing
   evaluation preflight.

## Task 4: Browser verification

**Files:** none unless a defect is found

1. Start a clean local container.
2. At desktop width, load the story, search the primary user's updated meeting,
   switch users, and confirm the foreign memory is absent.
3. Add a custom memory and retrieve it.
4. Start fresh and confirm the visible state and namespace change.
5. Repeat the core flow at 375px and check for horizontal overflow.
6. Inspect console errors and failed API requests; fix any defect and rerun.

## Task 5: Final gates and delivery

1. Run Ruff, Mypy, all Pytest tests, and compileall.
2. Run `git diff --check` and review the exact diff.
3. Commit with the repository Lore trailers, push `main`, and wait for GitHub
   Actions to pass.
4. Open `/demo` for the user and explain the write, index, isolation, retrieval,
   and evidence-return mechanism using the demonstrated flow.
