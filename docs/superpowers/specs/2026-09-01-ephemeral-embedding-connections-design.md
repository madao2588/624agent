# Ephemeral Embedding Connections Design

## Goal

Let a local user choose lexical retrieval, the OpenAI embedding service, or a
custom OpenAI-compatible embedding service from the demo page and supply their
own API key without persisting or logging the secret.

## User flow

1. The demo starts in the existing free lexical mode.
2. The user opens the semantic retrieval panel and chooses `OpenAI` or
   `OpenAI-compatible`.
3. The user enters an API key, model, and (for the custom option) base URL.
4. `Test and connect` performs one real embedding request. On success the server
   returns an opaque connection ID and non-secret metadata.
5. The page keeps only the connection ID in `sessionStorage`. Add and Search
   send it in `X-Embedding-Connection` while preserving the leaderboard JSON
   contract.
6. `Disconnect` deletes the in-memory connection and the browser token.

## API

- `POST /v1/embedding-connections` validates and tests a connection.
- `GET /v1/embedding-connections/{connection_id}` reports non-secret metadata
  and refreshes neither the key nor the TTL.
- `DELETE /v1/embedding-connections/{connection_id}` removes the connection.
- `/v1/memories/add` and `/v1/memories/search` accept an optional
  `X-Embedding-Connection` header. Without it, existing startup configuration
  remains unchanged.

Connection responses contain provider, model, base URL, and expiry time, but
never the API key. Unknown or expired IDs return HTTP 401. Embedding service
failures return HTTP 503 with sanitized messages.

## Runtime model

An `EmbeddingConnectionRegistry` owns a process-local, lock-protected map. Each
entry holds an `OpenAICompatibleEmbedder`, public metadata, and monotonic last
use time. IDs come from `secrets.token_urlsafe`. Connections expire after 30
minutes of inactivity and are lost on process restart.

Dynamic requests construct a short-lived `MemoryService` with the existing
SQLite store, a `HybridRetrievalPipeline`, and the connection's embedder. The
default singleton service remains the lexical or environment-configured path.
Vectors retain their model identifier, so incompatible vector models do not
mix during search. Dynamic connections derive a stable internal vector-space
identifier from provider, normalized base URL, and public model name. This
prevents two different providers that reuse the same model label from mixing
incompatible vectors; the public response still shows the user's model name.

## Security boundaries

- Keys are accepted only in the connection request body and represented as
  `SecretStr` during validation.
- Keys are never returned, logged, stored in SQLite, or written to browser
  storage.
- Base URLs must use HTTP or HTTPS, must not contain URL credentials, and must
  include a hostname.
- The browser stores only the opaque connection ID in `sessionStorage`.
- This is a local convenience boundary, not a multi-tenant secret vault.

## Verification

Tests cover connection creation, real probe injection, secret redaction,
dynamic semantic Add/Search, expiry, deletion, invalid IDs, URL validation,
unchanged lexical behavior, and the demo controls. Full lint, type checking,
unit tests, compile checks, and a real browser/API smoke path remain required.
