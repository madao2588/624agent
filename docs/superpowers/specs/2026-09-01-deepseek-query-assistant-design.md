# DeepSeek Query Assistant Design

## Goal

Let the demo connect to DeepSeek with a user-supplied API key and use the model
to improve memory search without pretending that DeepSeek is an embedding
model. The feature must remain optional, keep lexical mode free and local, and
preserve the existing embedding-provider path.

## What a vector model is

A vector model converts text into a fixed-length list of numbers. Texts with
similar meanings should produce nearby vectors, so retrieval can match meaning
even when the exact words differ. The current agent already supports that path
through OpenAI-compatible embedding APIs.

DeepSeek's public API exposes language-model endpoints rather than a dedicated
embedding endpoint. Therefore this integration uses DeepSeek as a query
expander: it turns one user search question into a small JSON list of related
terms, then the existing local lexical pipeline searches the SQLite memories.

## User flow

1. The demo starts in free local lexical mode.
2. The user chooses `DeepSeek · semantic query assistant`.
3. The user enters a DeepSeek API key and optionally changes the model. The
   default model is `deepseek-v4-flash`; the base URL is fixed to the official
   `https://api.deepseek.com` endpoint.
4. `Test and connect` performs one query-expansion probe and returns an opaque,
   process-local connection ID.
5. Adding a memory stays completely local. Searching sends only the search
   question to DeepSeek, receives related terms, and runs retrieval locally.
6. Disconnecting removes the process-local credential immediately. Inactivity
   also expires the connection after 30 minutes.

## Retrieval behavior

The DeepSeek request uses `POST /chat/completions`, JSON mode, temperature zero,
and a short response budget. The system prompt instructs the model to return a
JSON object containing at most 12 retrieval terms and never answer the user's
question. Returned data is validated for type, count, length, and blank values.

The local query-expansion pipeline combines the original question with the
validated terms, then delegates to the existing `LexicalRetrievalPipeline`.
Keeping the original query prevents a poor expansion from discarding exact
matches. State-chain, tag, bridge, user-isolation, and ranking behavior remain
owned by the existing retrieval pipeline.

If DeepSeek authentication, transport, rate limiting, or response validation
fails, Search returns a sanitized HTTP 503. It does not silently fall back,
because a visible failure makes connection problems diagnosable and avoids
giving the impression that semantic assistance succeeded.

## API compatibility

The provider-neutral surface is:

- `POST /v1/retrieval-connections`
- `GET /v1/retrieval-connections/{connection_id}`
- `DELETE /v1/retrieval-connections/{connection_id}`
- optional `X-Retrieval-Connection` on Add and Search

The previous `/v1/embedding-connections` routes and
`X-Embedding-Connection` header remain aliases so existing clients keep
working. Supplying conflicting values in both headers is rejected with HTTP
400. Public connection metadata includes a capability of `embedding` or
`query-expansion`, never the API key.

## Privacy and secret boundary

- DeepSeek receives the search question and the fixed instruction prompt only.
- Stored memory text, search results, database rows, user IDs, and prior
  searches are not included in the DeepSeek request.
- Add does not call DeepSeek.
- The key exists only in the backend process memory, is never logged or written
  to SQLite, and is represented in the browser only by an opaque connection ID
  kept in `sessionStorage`.
- This remains a local demo convenience, not a production multi-tenant vault.

## Verification

Tests cover request shape, JSON parsing, sanitized failures, query-only privacy,
Add-without-model-call, semantic retrieval through expansion, provider-neutral
routes and headers, backward-compatible aliases, secret redaction, and demo
copy. Full lint, typing, unit, compile, API smoke, and real-browser checks are
required before completion.
