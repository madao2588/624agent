# AML Memory Candidate

[![CI](https://github.com/madao2588/624agent/actions/workflows/ci.yml/badge.svg)](https://github.com/madao2588/624agent/actions/workflows/ci.yml)

A reproducible, evidence-first Add/Search memory service for the Agent Memory
Leaderboard Academic Textual Memory track.

The default configuration is a deterministic, credential-free structured
lexical system. It combines FTS5/BM25, CJK bigrams, source-backed facets,
event-state governance, preference/rule channels, and bounded three-hop
relations. An optional embedding adapter adds durable semantic vectors and
BM25 + Dense reciprocal rank fusion without changing the leaderboard contract.
All modes preserve raw messages and enforce exact user isolation. Ordinary
Chinese questions do not require spaces, colon tags, or another trigger syntax.

## What this service does

```text
Add -> idempotency -> local facets -> raw message + indexes + source relations
Search -> BM25 + facets + state + graph + intent -> grounded rerank -> evidence
```

With embeddings enabled:

```text
Add -> batch embedding -> raw message + FTS5 + vector in one SQLite transaction
Search -> BM25 candidates + cosine candidates -> RRF -> neighbors -> evidence
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
.\.venv\Scripts\python.exe -m pip install -e ".[dev,local]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn aml_memory.app:app --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000/demo> for the **Memory Playground**. It provides a
score-free, single-person conversation that writes three genuine multi-message
sessions: a preference, an appointment, and a later appointment update. Ask a
suggested question or add another turn to see the original evidence recalled.
The page writes through the same Add endpoint and searches through the same
retrieval pipeline used by the evaluation contract. It does not use a separate
demo store or generate prepared answers.

Use the default `MEMORY_AUTH_SCHEME=none` for this local browser experience.
"Start fresh" creates a new user namespace and leaves existing persisted data
untouched.

### Temporary browser-selected semantic retrieval

The playground starts in free local lexical mode. Open the collapsed
**Retrieval settings** panel to select free local semantic retrieval, DeepSeek,
OpenAI, or a custom OpenAI-compatible endpoint. Local semantic retrieval lazily
downloads the allowlisted quantized multilingual model (about 220 MB) on first
use and then runs it on this machine without an API key. All temporary local
connections share one in-process model instance, so opening another tab does
not load another copy. **Test and connect** performs one real provider probe.
Embedding providers switch subsequent
Add/Search calls to BM25 + Dense fusion. DeepSeek instead expands only each Search question into related terms;
the resulting lexical search remains local and Add never calls DeepSeek. Model
terms now supplement a partial BM25 match instead of being discarded as soon as
one local result exists. Supplemental evidence is accepted only from a leading
matched session or through a source-text entity anchor.

The hybrid path also has a narrow session-to-turn decomposition for prospective
age questions. It keeps the direct event evidence first, uses that source only
as a local FTS topic bridge to shortlist related sessions, and searches those
sessions for an explicit current-age statement. The derived query never guesses
the age or answer, and source memory text is not sent to an external query
expander. Diagnostics label this route `session-vector`.

Local semantic text never leaves the machine. External-provider API keys are
never written to SQLite, API responses, or application logs. By
default the browser keeps only an opaque connection ID in `sessionStorage`.
When **Remember this Key in this browser** is selected, the playground also
stores the selected provider configuration and Key in that browser's
`localStorage` so it can reconnect after a reload. This is convenient but should
only be used on a trusted personal device; **Disconnect and clear key** removes
both the server-side connection and the saved browser value.

### Recall diagnostics

After a successful recall, the playground shows why each source was retrieved,
its structured facets, a current/history/cancelled/forgotten timeline, and a
bounded relation graph. These views come from
`POST /v1/memories/search/diagnostics`, which shares the same authentication,
user isolation, connection selection, and retrieval pipeline as ordinary
Search. The diagnostics route is intentionally excluded from OpenAPI and the
leaderboard contract; `/v1/memories/search` retains its exact evidence-only
response.

The provider-neutral API is:

```text
POST   /v1/retrieval-connections
GET    /v1/retrieval-connections/{connection_id}
DELETE /v1/retrieval-connections/{connection_id}
```

Add/Search keep their leaderboard-compatible JSON bodies. A client opts into
the temporary connection with this header:

```text
X-Retrieval-Connection: <opaque connection_id>
```

The former `/v1/embedding-connections` routes and
`X-Embedding-Connection` header remain compatibility aliases.
`provider: "openai"` fixes the base URL to `https://api.openai.com/v1`.
`provider: "openai-compatible"` requires an HTTP(S) base URL without embedded
credentials, query parameters, or fragments. Connect before Add: messages
written in lexical mode do not have vectors to backfill automatically.

`provider: "local"` accepts neither a key nor a custom URL and uses only
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. This allowlist
prevents API callers from making the service download arbitrary models or open
local model paths. Install `.[local]` when running outside the supplied Docker
image; the image already includes the local runtime.

`provider: "deepseek"` fixes the base URL to `https://api.deepseek.com` and
defaults to `deepseek-v4-flash`. DeepSeek's public API is used as a language
model, not an embedding model: the request contains the current search question
and a fixed JSON instruction only. Stored memory text, results, user IDs, and
prior searches are not sent. Provider failures return a sanitized 503 instead
of silently falling back to lexical mode.

Run the real HTTP smoke test in another terminal:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py http://127.0.0.1:8000
```

### Readable offline memory challenges

To inspect memory behavior without an API key, external model, generated
answer, or leaderboard result, run:

```powershell
.\.venv\Scripts\python.exe scripts\run_memory_challenges.py
```

The checked-in corpus contains 20 legal synthetic scenarios covering explicit
facts, cross-language recall, options, alias/coreference, relative time,
update/cancel/resume/forget governance, two- and three-hop relations,
preferences, habits, procedures, prompt-injection memories, and abstention. For
each question the runner prints the expected source excerpt and every raw
evidence message returned by the real pipeline. Its Recall@K, MRR, nDCG, noise,
abstention, and latency footer is local diagnostic output, not an official
benchmark score.

The cases live in [`evaluation/memory_challenges.json`](evaluation/memory_challenges.json)
and can be replaced with another compatible file using `--cases`.

### Public LongMemEval-S evidence evaluation

For a reproducible test on a public long-conversation corpus, download the
official cleaned LongMemEval-S file (about 277 MB) and run the checked-in
adapter. The dataset is intentionally not committed to this repository.

```powershell
New-Item -ItemType Directory -Force artifacts\longmemeval\data | Out-Null
Invoke-WebRequest `
  -Uri "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json?download=true" `
  -OutFile artifacts\longmemeval\data\longmemeval_s_cleaned.json

# Quick stratified run: the first five records from each question type.
.\.venv\Scripts\python.exe scripts\run_longmemeval.py `
  --data artifacts\longmemeval\data\longmemeval_s_cleaned.json `
  --output-dir artifacts\longmemeval\stratified-30 `
  --cutoffs 1,5,10 `
  --per-type-limit 5

# Run the same protocol with the free local multilingual embedding model.
# The first run downloads the model; long histories take materially longer to index.
.\.venv\Scripts\python.exe scripts\run_longmemeval.py `
  --data artifacts\longmemeval\data\longmemeval_s_cleaned.json `
  --output-dir artifacts\longmemeval\local-semantic-stratified-30 `
  --cutoffs 1,5,10 `
  --per-type-limit 5 `
  --retrieval-mode local-semantic

# Full 500-question corpus. Retrieval metrics exclude the 30 abstention cases.
.\.venv\Scripts\python.exe scripts\run_longmemeval.py `
  --data artifacts\longmemeval\data\longmemeval_s_cleaned.json `
  --output-dir artifacts\longmemeval\full-500 `
  --cutoffs 1,5,10
```

Each run writes one inspectable JSONL record per question plus `summary.json`
and `report.md`. The report contains session- and turn-level Recall-any,
Recall-all, and nDCG, including breakdowns for all six question types. It also
records the dataset SHA-256, filters, ingestion and retrieval modes, and the fact that no
answer reader or LLM judge was used. Each question requests the contract's
`top_k=100`; @1, @5, and @10 are prefixes of that one ordered result.

The runner indexes both user and assistant source turns because the service's
Add contract stores both roles and 51 cleaned non-abstention cases have gold
evidence only on assistant turns. The older upstream retrieval helper indexes
user turns only and omits those cases, so treat this report as the service's
all-role evidence protocol rather than a directly comparable upstream BM25
baseline.

The default `benchmark-lexical` ingestion mode preserves the official raw
message, session, timestamp, and answer-turn mapping while indexing only the
source text needed for BM25 retrieval. It deliberately skips production facet,
state, and relation enrichment so hundreds of isolated histories can be
replayed in minutes. Use `--ingestion-mode full` on a bounded selection when
you specifically want to exercise the complete Add enrichment path.

This is still a **local labelled-source retrieval evaluation, not an official
leaderboard score**: it does not generate answers, call the benchmark's reader
model, or run an LLM judge. The current reproducible results and limitations are
documented in [`docs/longmemeval-s-results.md`](docs/longmemeval-s-results.md).

Explicit updates and source-backed structured event changes can create durable
state relations when the new and prior messages share strong anchors. Current
queries prefer active or resumed evidence; history queries retain the auditable
older chain. Cancelled and forgotten memories are kept for explicit history but
stay out of ordinary recall. Conversational references such as `previous chat`
or `previous conversation` use normal relevance ranking; they no longer trigger
oldest-state ordering unless the question also explicitly asks for the original,
earliest, or historical state.

Source messages with explicit preference language (`prefer`, `favorite`,
`avoid`, `dislike`, `喜欢`, `偏爱`) or procedure language (`must`, `before`,
`never`, `if`, `必须`, `步骤`) receive a user-isolated auxiliary tag in the
same Add transaction. Preference/procedure questions can use the corresponding
bounded tag channel when ordinary wording does not overlap. Tags point only to
raw sources: the service does not turn one behavior into an inferred profile or
invent a procedural answer.

## Docker

```powershell
docker build -t aml-memory-v1 .
docker run --rm -p 8000:8000 -v aml-memory-data:/data aml-memory-v1
```

The image runs as a non-root user and stores SQLite data at `/data/memory.db`.

## Leaderboard evaluation preflight

This repository follows the **Academic Methods / Textual Memory / Code
Submission** route. Maintainers can build the public repository with Docker and
call the official synchronous Add/Search contract. No Leaderboard Eval Key is
required for the code-submission route.

Run the black-box contract preflight against a live service:

```powershell
.\.venv\Scripts\python.exe scripts\eval_preflight.py `
  --base-url http://127.0.0.1:8000 `
  --add-concurrency 64 `
  --search-concurrency 256
```

The installed command is equivalent:

```powershell
.\.venv\Scripts\aml-eval-preflight.exe --base-url http://127.0.0.1:8000
```

The preflight checks unauthenticated Health, exact Add ID echoes, synchronous
visibility, idempotency, options-assisted Search, Top K, stable ordering,
cross-user isolation, and concurrent Add/Search. It prints only stage counts
and timings.

A local preflight pass is compatibility evidence, **not an official leaderboard
score**. The platform owns Answer, Eval, result review, and publication. The
prepared submission notes are in [`evaluation/SUBMISSION.md`](evaluation/SUBMISSION.md).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEMORY_DB_PATH` | `data/memory.db` | SQLite database path |
| `MEMORY_RUNTIME_MODE` | `local` | `local` or frozen `evaluation` runtime |
| `MEMORY_NEIGHBOR_RADIUS` | `1` | Same-session messages on each side of a hit |
| `MEMORY_AUTH_SCHEME` | `none` | `none`, `token`, `bearer`, or `x-api-key` |
| `MEMORY_API_KEY` | unset | Required when authentication is enabled |
| `MEMORY_EMBEDDING_PROVIDER` | `none` | `none` or `openai-compatible` |
| `MEMORY_EMBEDDING_API_KEY` | unset | Required when embeddings are enabled |
| `MEMORY_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model ID |
| `MEMORY_EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API root |
| `MEMORY_EMBEDDING_DIMENSIONS` | unset | Optional output dimension override |
| `MEMORY_EMBEDDING_TIMEOUT_SECONDS` | `30` | Embedding HTTP timeout |
| `MEMORY_EVALUATION_API_KEY` | unset | Required only in `evaluation` mode |
| `MEMORY_EVALUATION_MODEL` | `gpt-4o-mini` | Fixed; any other value fails startup |
| `MEMORY_EVALUATION_PROFILE` | `evaluation/evaluation-profile.json` | Checked-in frozen evaluation settings |

See [`.env.example`](.env.example) for safe local defaults and placeholders.
Real credentials must be injected at runtime and must not be committed.

Health remains public when API authentication is enabled. Add/Search and their
compatibility aliases require the configured credential. Secrets are read only
from environment variables and are never accepted as preflight CLI values.
The `none` default is intended for local development and public compatibility
smoke only. A formal deployment should enable the authentication scheme bound
in the evaluation request.

Example authenticated container:

```powershell
$env:MEMORY_API_KEY = "replace-with-a-generated-secret"
docker run --rm -p 8000:8000 `
  -e MEMORY_AUTH_SCHEME=bearer `
  -e MEMORY_API_KEY `
  -v aml-memory-data:/data `
  aml-memory-v1
```

Run the authenticated preflight without placing the key in shell history:

```powershell
.\.venv\Scripts\python.exe scripts\eval_preflight.py `
  --base-url http://127.0.0.1:8000 `
  --auth-scheme bearer `
  --api-key-env MEMORY_API_KEY
```

No external model key is required for the default lexical implementation.
To enable semantic retrieval, set the provider, API key, and model before
starting the service:

```powershell
$env:MEMORY_EMBEDDING_PROVIDER = "openai-compatible"
$env:MEMORY_EMBEDDING_API_KEY = "replace-with-your-key"
$env:MEMORY_EMBEDDING_MODEL = "text-embedding-3-small"
.\.venv\Scripts\python.exe -m uvicorn aml_memory.app:app --host 0.0.0.0 --port 8000
```

The adapter sends message text and search queries to the configured embedding
service. The API key is read only from the environment and is not stored or
logged. If the provider is enabled but unavailable, Add/Search returns 503
instead of silently changing retrieval behavior. Add creates all message
vectors before opening the SQLite write transaction, then commits messages,
FTS rows, and vectors atomically.

The current durable vector backend calculates cosine similarity with a bounded
candidate pipeline but scans the selected user's compatible SQLite vectors in
Python. It is deliberately dependency-free and suitable for local demos and
correctness regression. Before million-scale use, replace that store method
with sqlite-vec, FAISS, or a vector service; the Embedder, retrieval pipeline,
and HTTP contract do not need to change.

### Frozen evaluation mode

Formal evaluation runs separately from the playground's temporary provider
connections. Start it with:

```powershell
$env:MEMORY_RUNTIME_MODE = "evaluation"
$env:MEMORY_EVALUATION_API_KEY = "replace-with-your-openai-api-key"
python -m uvicorn aml_memory.app:app --host 0.0.0.0 --port 8000
```

The checked-in profile fixes `gpt-4o-mini`, Add enrichment, Search planning,
candidate limits, three-hop graph traversal, timeout, two attempts, and a
bounded circuit breaker. Add uses the Responses API with strict structured
output to attach source-backed retrieval facets; Search uses the same fixed
model for bounded query terms. Both calls set `store: false`. A repeated
identical Add is resolved before the provider call. Provider failures return a
sanitized 503 and never cause a partial write or silent local fallback.

Temporary DeepSeek/embedding connection headers are rejected in evaluation
mode so a caller cannot alter the frozen method. Search still returns only raw
messages stored for the requested `user_id`; model output is never returned as
evidence.

## Verification

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src tests scripts
.\.venv\Scripts\python.exe scripts\scan_secrets.py
```

The regression suite covers API validation, synchronous visibility,
idempotency conflicts, strict user isolation, special FTS input, context
expansion, explicit state chains, preference/procedure intent channels,
timestamp fidelity, concurrent retries, restart recovery, and log payload
safety. GitHub Actions repeats these checks, builds the Docker image, starts an
ephemeral container, and runs the complete evaluation preflight.

## Current boundary

The default remains free and deterministic. Evaluation mode adds a fixed model
dependency but does not turn the service into an answer generator: raw source
messages remain the only returned evidence. The SQLite vector path intentionally
uses a bounded Python cosine scan and is not intended for million-scale hosting.
The included synthetic metrics are regression diagnostics and no official
leaderboard score is claimed.

The approved design and implementation plan are kept under
`docs/superpowers/`.
