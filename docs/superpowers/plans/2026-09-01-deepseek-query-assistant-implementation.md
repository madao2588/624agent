# DeepSeek Query Assistant Implementation Plan

1. Add failing query-expander tests.
   - Verify the official chat-completions URL, bearer authentication, JSON-mode
     request, model, prompt boundary, parsed terms, and sanitized failures.
   - Acceptance: tests fail because the DeepSeek expander does not exist.
2. Add failing retrieval and API tests.
   - Prove expansion can retrieve a paraphrased memory, DeepSeek sees only the
     search query, Add makes no model call, generic routes/headers work, and old
     embedding aliases remain compatible.
   - Acceptance: tests fail at the missing pipeline and provider support.
3. Implement the provider adapter and retrieval pipeline.
   - Use the standard library HTTP client; introduce no dependency.
   - Validate and bound all model output before combining it with the original
     query and delegating to lexical retrieval.
   - Acceptance: unit tests pass and all provider errors are secret-safe.
4. Generalize the transient connection surface.
   - Support `embedding` and `query-expansion` capabilities in the in-memory
     registry, add provider-neutral routes/header, and retain old aliases.
   - Acceptance: existing embedding tests plus new DeepSeek API tests pass.
5. Update the demo and README.
   - Add the DeepSeek preset, provider-specific defaults, explicit privacy text,
     generic connection storage/header wiring, and concise usage instructions.
   - Acceptance: demo assertions pass and the UI makes clear what leaves the
     machine.
6. Run full verification.
   - Ruff, mypy, pytest, compileall, offline challenge suite, secret checks,
     HTTP smoke, and desktop/mobile browser console/network inspection.
   - Acceptance: every command exits zero; no known console error, failed API,
     secret persistence, or regression remains.
