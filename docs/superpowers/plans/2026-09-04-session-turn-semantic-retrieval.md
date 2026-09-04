# Session-to-turn semantic retrieval

**Goal:** Recover supporting turns for multi-hop questions when the system has
identified the right conversation but the original question is not similar to
every required fact.

## Failure to fix

The LongMemEval case `ba358f49` asks how old the user will be when Rachel gets
married. The existing hybrid search retrieves the turn saying Rachel marries
next year, and it also ranks the separate age conversation as a relevant
session, but it misses the exact turn saying the user is 32. That age sentence
has low similarity to the full question, even though it is the missing operand
needed to answer it.

## Design

1. Keep lexical and full-query vector retrieval as the session-discovery stage.
2. Detect only well-defined prospective-age questions and derive a non-answering
   semantic component such as `my current age how old I am`.
3. Use the strongest lexical evidence as a local topic bridge, then combine
   those related sessions with a bounded shortlist from the unfiltered
   full-query vector ranking. Low-similarity turns may nominate a session, but
   they cannot enter the final evidence by themselves.
4. Search each component only inside those candidate sessions. Component hits
   must still pass the normal similarity threshold.
5. Keep the strongest original result first and reserve the next evidence slot
   for the best `session-vector` operand. Broad graph expansion therefore cannot
   evict the required second fact; ordinary queries keep their existing path.

This is deliberately narrower than generating arbitrary query expansions. The
derived component never guesses the user's age or the final answer; it only
states which missing fact should be retrieved.

## Safety and limits

- Session-scoped vector search must preserve both user and embedding-model
  isolation in SQL.
- Candidate sessions and per-session turns are capped to bound latency.
- No memory text is sent outside the configured embedding provider.
- If the six-type regression sample loses any existing recall, do not ship the
  ranking change.

## Verification

- Store regression: a session filter cannot return another session or user.
- Retrieval regression: a two-session future-age question retrieves both the
  event turn and a semantically hidden current-age turn.
- Existing unit, lint, type and compilation checks.
- Re-run the real failing LongMemEval case and the frozen six-question sample,
  comparing session/turn recall and nDCG with the previous result.

## Measured result

On `ba358f49`, the two labelled turns moved to ranks 1 and 2. Both session and
turn `recall_all@5` improved from 0 to 1, and nDCG@5 improved from 0.5 to 1.0.
Across the frozen six-question sample, no other case changed: turn nDCG@5 rose
from 0.6192 to 0.7026 and average search latency rose from 293.76 ms to
305.68 ms.
