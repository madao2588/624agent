# AML Memory Candidate

A reproducible, evidence-first Add/Search memory service for the Agent Memory
Leaderboard Academic Textual Memory track.

This repository intentionally starts with a deterministic lexical baseline.
It preserves raw messages, enforces exact user isolation, expands same-session
context, and leaves stable extension points for embeddings, rank fusion,
reranking, temporal governance, and agentic query planning.

## What this service does

```text
Add -> validate -> idempotent SQLite transaction -> raw message + FTS5 index
Search -> safe FTS5 query -> user-filtered hits -> neighbor expansion -> evidence
```

The service returns memory evidence only. It does not generate or disguise a
final answer; the leaderboard owns the shared Answer and Evaluation stages.

## Contract endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Unauthenticated health probe |
| `POST` | `/v1/memories/add` | Synchronous durable Add |
| `POST` | `/v1/memories/search` | Ordered evidence Search |

`/add` and `/search` are compatibility aliases.

### Add

```json
{
  "request_id": "demo-request-1",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "I adopted a cat named Luna."
    }
  ],
  "user_id": "demo-user-1",
  "session_id": "demo-session-1"
}
```

The endpoint returns HTTP 200 only after every message and its FTS index are
committed and immediately searchable. Repeating the same `request_id` and
payload is idempotent. Reusing the ID with a different payload returns 409.

### Search

```json
{
  "query": "What is the name of my cat?",
  "options": ["Luna", "Milo"],
  "user_id": "demo-user-1",
  "top_k": 100
}
```

```json
{
  "data": [
    {
      "id": "mem_...",
      "content": "[2024-01-01T00:00:00Z] USER: I adopted a cat named Luna.",
      "score": 1.0,
      "created_at": "2026-09-01T00:00:00Z"
    }
  ]
}
```

The Search pipeline applies `user_id` in both candidate lookup and source-row
lookup. Neighbor expansion is constrained to the same user and session.

## Local development

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn aml_memory.app:app --host 0.0.0.0 --port 8000
```

Run the real HTTP smoke test in another terminal:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py http://127.0.0.1:8000
```

## Docker

```powershell
docker build -t aml-memory-v1 .
docker run --rm -p 8000:8000 -v aml-memory-data:/data aml-memory-v1
```

The image runs as a non-root user and stores SQLite data at `/data/memory.db`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEMORY_DB_PATH` | `data/memory.db` | SQLite database path |
| `MEMORY_NEIGHBOR_RADIUS` | `1` | Same-session messages on each side of a hit |

No external model or API key is required for V1.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
```

The regression suite covers API validation, synchronous visibility,
idempotency conflicts, strict user isolation, special FTS input, context
expansion, timestamp fidelity, concurrent retries, restart recovery, and log
payload safety.

## Current boundary and next version

V1 is a reliable lexical baseline, not a claim of leaderboard competitiveness.
The next version will add a pluggable OpenAI-compatible embedding adapter,
durable vectors, Dense + BM25 Reciprocal Rank Fusion, and end-to-end regression
against the leaderboard's public evaluation pipelines. Raw source messages will
remain the only returned evidence.

The approved design and implementation plan are kept under
`docs/superpowers/`.
