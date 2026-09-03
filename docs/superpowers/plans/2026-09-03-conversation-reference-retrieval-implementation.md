# Conversation Reference Retrieval Implementation Plan

1. Add an integration test proving `previous chat` preserves lexical relevance
   instead of forcing oldest-first ranking.
   **Acceptance:** the test fails on the current implementation.
2. Separate explicit history intent from conversational references in
   `_is_history_query` without changing the Search API.
   **Acceptance:** the new test and structured current/history tests pass.
3. Run the same 30-case stratified LongMemEval-S selection and compare it with
   the frozen artifact. Continue to all 500 cases only when the sample is safe.
   **Acceptance:** retain only a non-regressing implementation.
4. Update measured documentation and run the complete local and GitHub
   verification chain.
   **Acceptance:** all checks pass and the remote commit matches local HEAD.
