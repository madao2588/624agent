# Bilingual DeepSeek Recall Implementation Plan

1. Add failing provider-contract tests in `tests/test_query_expansion.py`.
   - Assert the DeepSeek prompt explicitly requires Chinese and English search
     phrases while still sending only the current question.
   - Acceptance: the new assertion fails against the current prompt.
2. Add failing retrieval scenarios in `tests/test_retrieval.py`.
   - Cover Chinese question to English memory and English question to Chinese
     memory, plus diverse personal-memory behaviors.
   - Acceptance: tests demonstrate the exact expansion terms needed for local
     evidence recall and preserve user isolation/zero-hit behavior.
3. Strengthen the DeepSeek retrieval prompt in
   `src/aml_memory/query_expansion.py`.
   - Keep JSON validation, secret handling, request shape, and the query-only
     privacy boundary unchanged.
   - Acceptance: provider-contract tests pass.
4. Correct search feedback and mode descriptions in
   `src/aml_memory/demo.html`.
   - Report actual result count, distinguish zero hits, and call the DeepSeek
     feature bilingual query expansion.
   - Acceptance: demo source tests and real-browser checks pass.
5. Run focused tests, full lint/type/test/static checks, the offline challenge
   runner, GitNexus change detection, and browser scenarios.
   - Acceptance: all commands exit successfully and no unrelated execution
     flows are reported.
