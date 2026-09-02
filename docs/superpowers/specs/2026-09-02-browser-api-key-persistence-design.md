# Browser API Key Persistence Design

## Goal

Keep the retrieval provider API key available across browser restarts so the
local demo can reconnect without asking the user to re-enter it.

## Boundary

- Persist provider, model, optional base URL, and API key in this browser's
  `localStorage` for the current origin.
- Keep the existing server-side connection opaque and process-local.
- Never write the key to SQLite, application logs, repository files, or API
  responses.
- Keep the API key input masked.
- Make removal explicit: the disconnect action deletes both the active server
  connection and the saved browser configuration.
- If browser storage is unavailable or malformed, fall back to the free local
  lexical mode without breaking the page.

## Startup behavior

1. Read and validate the saved configuration.
2. Restore the form fields.
3. Reuse a still-live session connection when available.
4. Otherwise recreate the connection using the saved key.
5. Report a connection error without deleting the saved configuration, so a
   temporary network failure does not force the user to enter the key again.

## Security tradeoff

`localStorage` is convenient but is readable by JavaScript running on the same
origin. The page therefore labels the behavior, provides a clear removal
control, and limits the design to this local demo. It is not a server-side
secret store.
