# Ephemeral Embedding Connections Implementation Plan

1. Add failing schema and registry tests.
   - Cover URL validation, secret-safe response models, 30-minute inactivity
     expiry, deletion, and opaque IDs.
   - Acceptance: tests fail because the connection registry does not exist.
2. Implement the in-memory registry and connection models.
   - Add a clock-injectable, lock-protected registry with sanitized metadata.
   - Acceptance: registry unit tests pass without exposing an API key.
3. Add failing API tests.
   - Inject an embedder factory, create/test a connection, use its header for
     semantic Add/Search, then delete and reject it.
   - Acceptance: tests fail because the API routes/header behavior are absent.
4. Implement connection routes and per-request service selection.
   - Preserve existing Add/Search bodies and authentication.
   - Acceptance: API tests pass; requests without the header keep existing
     lexical behavior.
5. Add failing demo assertions and implement the connection panel.
   - Add provider/model/base URL/key fields, connect/disconnect controls,
     accessible status text, sessionStorage for the ID only, and header wiring.
   - Acceptance: demo tests and manual browser flow pass.
6. Document operation and boundaries.
   - Explain the UI flow, API routes, TTL, key handling, and provider presets.
   - Acceptance: README examples match the tested interface.
7. Run full verification.
   - Ruff, mypy, pytest, compileall, secret scans, HTTP smoke, and browser
     console/network checks.
   - Acceptance: all commands exit zero and no secret appears in responses,
     logs, database bytes, or browser storage.
