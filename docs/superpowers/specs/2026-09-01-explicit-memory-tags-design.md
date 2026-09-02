# Explicit Memory Tags Design

**Status:** approved through delegated implementation authority on 2026-09-01

## Goal

Recover explicit preference and procedure evidence when the question expresses
the same intent with different vocabulary and the no-model lexical path has no
direct hit.

The feature classifies source messages into two conservative auxiliary kinds:

- `preference`: explicit like, dislike, favorite, avoidance, or repeated-choice
  language;
- `procedure`: explicit requirement, order, condition, prohibition, or step
  language.

The tag points to an immutable source message. It is not an extracted answer,
summary, or inferred user profile.

## Add behavior

During the existing SQLite transaction, deterministic marker rules classify
each newly inserted source message. Matching kinds are written to a
`message_tags` table containing `message_id`, `user_id`, `kind`, and
`created_at`. Repeated Add is idempotent through the table primary key and the
existing request contract.

## Search behavior

The query is independently classified for preference or procedure intent. For
each detected intent, Search reads a bounded set of same-user tagged source
messages. Direct BM25/vector evidence keeps its stronger score; intent-only
evidence enters at a lower score, ordered by source time. Existing state-chain,
entity-bridge, neighbor, `top_k`, and original-evidence rules remain in force.

The intent channel is bounded to at most 100 tagged candidates per query and is
never recursively expanded as another intent.

## Safety and tradeoffs

- Tags require explicit linguistic markers; implicit behavior is intentionally
  missed rather than freely inferred.
- A broad preference question may retrieve several explicit preferences. This
  improves recall but can add noise when a user has more than 100 such sources.
- Tags never cross `user_id` and never alter source content.
- A later embedding or model-assisted classifier can implement the same
  storage and retrieval contract without changing the leaderboard response.

## Acceptance criteria

- Preference and procedure tags persist across restart and are idempotent.
- Tag reads enforce `user_id` even when passed another user's message context.
- Preference/procedure questions with no lexical overlap retrieve the explicit
  tagged source.
- Ordinary factual questions do not activate the tag channel.
- Existing state, vector, API, and challenge tests remain green.
