# Explicit State Chain Design

**Status:** approved through delegated implementation authority on 2026-09-01

## Goal

Represent explicit updates as durable, user-isolated `supersedes` links so a
current-state query can retrieve a replacement even when the replacement no
longer contains every word from the original fact.

Example:

```text
Old: The Atlas launch briefing is Friday morning in Room 8.
New: The Atlas briefing has been rescheduled to Monday afternoon in Room 12.
```

A query for the "current launch" directly matches only the old source. The
state link must bring the new source into the result, rank it first, and retain
the old source as change history.

## Chosen approach

Use a conservative deterministic linker during the existing SQLite Add
transaction. A new message is eligible only when it contains an explicit
update signal such as `moved`, `changed`, `rescheduled`, `no longer`, `改到`,
`改为`, or `不再`. It may supersede the most recent earlier message only when
the two messages share at least two non-trivial topic terms.

This is preferred over recency-only guessing because an unrelated recent
message is not automatically treated as a replacement. It is preferred over an
LLM extractor for this iteration because the system must remain offline,
deterministic, and free of external latency.

## Data model

Add a `state_relations` table:

- `newer_message_id`
- `older_message_id`
- `user_id`
- `relation` fixed to `supersedes`
- `created_at`

Both ends remain immutable rows in `messages`. The relation is an auxiliary
index and is never returned as generated evidence. Foreign keys, a composite
primary key, and duplicated `user_id` checks preserve provenance and isolation.

## Add behavior

1. Begin the existing immediate transaction and resolve idempotency.
2. Insert each source message and FTS row.
3. If the source contains an explicit update signal, use its topic terms to
   retrieve a bounded set of earlier same-user candidates through FTS.
4. Select the most recent candidate that shares at least two topic terms and
   does not occur after the update.
5. Insert one `supersedes` relation in the same transaction.
6. Commit source messages, vectors, and state links together.

No relation is created for ordinary statements or weak one-word overlap.

## Search behavior

For queries that explicitly request the current/latest state:

1. Run the existing lexical or hybrid retrieval.
2. Expand any connected `supersedes` chain within the same user, bounded to
   eight relation steps and the existing candidate budget.
3. Rank the newest timestamped source first, then older sources.
4. Continue with existing entity and same-session neighbor expansion.

Historical queries without current-state intent retain their existing ranking.

## Non-goals and known limits

- No implicit contradiction detection.
- No semantic matching between unrelated wording.
- No replacement link from only one generic shared word.
- No deletion or rewriting of old facts.
- No claim that deterministic links cover all benchmark updates.

The table and retrieval interface are intentionally compatible with a later
LLM-backed linker, but this iteration does not add one.

## Acceptance criteria

- The relation persists across store restarts and repeated Add remains
  idempotent.
- Cross-user chains are impossible in both writes and reads.
- A current-state query that directly matches only the old fact returns the
  explicit replacement first and the old fact afterwards.
- Unrelated messages and weak overlaps do not create a relation.
- Existing raw evidence, API contract, vector path, and challenge behavior are
  unchanged.
