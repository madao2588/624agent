# Browser API Key Persistence Implementation Plan

1. Extend the demo regression test with the new persistence contract.
   - Assert the page exposes a remember-key control and browser-storage notice.
   - Assert `localStorage` is used for provider configuration while
     `sessionStorage` remains limited to the opaque connection ID.
   - Run the focused test and confirm it fails before implementation.

2. Add the minimal persistence UI and JavaScript.
   - Add an enabled-by-default remember checkbox and clarify the local-browser
     storage boundary.
   - Store validated provider configuration only after a successful connection.
   - Restore form values and reconnect automatically during startup.
   - Clear saved configuration and the active connection on explicit removal.
   - Treat blocked or malformed storage as a non-fatal fallback.

3. Verify behavior and scope.
   - Run the focused demo tests, then the complete test suite, Ruff, mypy, and
     compileall.
   - Exercise save, reload/reconnect, and clear in a real browser.
   - Run GitNexus change detection and confirm only the demo flow and its tests
     are affected.
