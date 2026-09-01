# Agent Memory Leaderboard Submission Notes

This document prepares the repository for the Academic Methods code-submission
route. Replace every `TODO(before submission)` value before sending the official
access request.

## Identity

- System name: AML Memory Candidate
- Version: 0.1.0 evaluation-preflight baseline
- Fixed Git commit: `TODO(before submission): insert immutable commit SHA`
- Repository: <https://github.com/madao2588/624agent>
- Contact: `TODO(before submission)`
- Team / affiliation: `TODO(before submission)`
- Evaluation type: Textual Memory
- Participant division: Academic Methods
- Submission route: Public code; platform Docker deployment

## Current evaluation status

- Local contract preflight: implemented
- Repository CI: implemented
- Platform smoke: not run; requires an accepted evaluation request
- Official full evaluation: not run
- Official score: none

The repository does not claim that local tests reproduce the platform's private
Answer, Eval, dataset bundle, or aggregation pipeline.

## Reproduction

Build:

```bash
docker build -t aml-memory-candidate:0.1.0 .
```

Run with ephemeral storage:

```bash
docker run --rm --name aml-memory-candidate \
  -p 8000:8000 \
  aml-memory-candidate:0.1.0
```

Run with persistent storage:

```bash
docker run --rm --name aml-memory-candidate \
  -p 8000:8000 \
  -v aml-memory-data:/data \
  aml-memory-candidate:0.1.0
```

Endpoints:

- Health: `GET http://127.0.0.1:8000/health`
- Add: `POST http://127.0.0.1:8000/v1/memories/add`
- Search: `POST http://127.0.0.1:8000/v1/memories/search`

Run the black-box compatibility preflight from the checkout:

```bash
python -m pip install .
python scripts/eval_preflight.py \
  --base-url http://127.0.0.1:8000 \
  --add-concurrency 16 \
  --search-concurrency 32
```

## Authentication

Local development and the public compatibility smoke use
`MEMORY_AUTH_SCHEME=none`. Formal evaluation must use the authentication scheme
bound during the access request. The service supports `token`, `bearer`, and
`x-api-key` through `MEMORY_AUTH_SCHEME` plus `MEMORY_API_KEY`. Health is always
unauthenticated. No key is committed to the repository; the credential must be
delivered through the organizer's controlled channel and injected as an
environment variable.

## Capacity and persistence

- Add protocol: synchronous HTTP 200 after SQLite and FTS persistence
- Search protocol: synchronous ordered evidence response
- Database: SQLite WAL at `/data/memory.db`
- Local preflight concurrency: 16 Add workers and 32 Search workers
- Formal Top K supported: 100
- Retry safety: exact Add retries are idempotent by `request_id` and payload hash

These values describe verified compatibility settings, not a hosted-service SLA.

## Method and originality disclosure

This repository is an original competition implementation owned by its
contributors. It uses standard FastAPI, SQLite, and SQLite FTS5 capabilities;
it does not copy an external memory-agent repository or reproduce a specific
paper. The implementation was developed with OpenAI Codex assistance under
human direction and review.

Current method changes and design choices:

1. Raw source messages are preserved as auditable evidence.
2. Writes are transactional and idempotent.
3. Search enforces `user_id` in both the FTS candidate table and source table.
4. Question options participate in lexical retrieval.
5. Same-session neighbors are expanded and relevance-ranked.
6. Search never generates a final answer.

The current version does not call an LLM during Add or Search. Any future model,
embedding, reranking, repository, or paper reuse must be disclosed here before
the evaluated version is frozen.

## Data handling

- Evaluation data is used only to execute the requested evaluation.
- Request bodies and API keys are not logged.
- Evaluation databases and derived data must be deleted within 30 days after a
  job completes unless the organizers grant written permission to retain them.
- Cross-`user_id` retrieval is prohibited and covered by regression tests.

## Before submitting

1. Fill the contact and team fields.
2. Complete retrieval-quality improvements before consuming the scarce full run.
3. Rerun CI and the Docker preflight from a clean checkout.
4. Insert the immutable commit SHA and create a signed or annotated release tag.
5. Verify the current competition dates and checklist in the official API Guide.
6. Ask the organizers to confirm how the `gpt-4o-mini` Full checklist applies to
   a deterministic Add/Search implementation that does not call any model.
7. Submit the evaluation access request after the next cycle opens.
