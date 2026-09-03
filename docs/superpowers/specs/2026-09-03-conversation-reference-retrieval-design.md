# Conversation Reference Retrieval Design

## Goal

Stop conversational framing such as "our previous chat" from being mistaken for
a request to rank the oldest historical state first.

## Evidence

In the frozen LongMemEval-S result, 51 answerable questions contain `previous`.
Forty-two are `single-session-assistant` questions, and only about 5% of that
slice retrieves a gold turn in the top five. The shared wording points back to a
conversation; it does not ask for the earliest version of a changing fact.

## Options considered

1. Remove `previous` from history detection entirely. Simple, but loses valid
   requests such as "the previous meeting time".
2. Treat explicit conversational references as neutral while retaining genuine
   history words such as `original`, `earliest`, and `history`. This is the
   selected option because it fixes the ambiguity without weakening state-chain
   history queries.
3. Ask an LLM to classify every query. More flexible, but makes the free local
   path network- and key-dependent.

## Behavior

`previous chat`, `previous conversation`, `previous discussion`, and `previous
game` are retrieval context, not history intent. A query containing one of those
phrases uses normal lexical relevance unless it also explicitly asks for
history, the original state, or the earliest state.

## Acceptance

- A conversational-reference regression test fails before implementation and
  passes afterward.
- Existing current/history state-chain tests remain unchanged.
- The 30-case stratified LongMemEval-S sample must not regress at Turn
  Recall-all@5 or nDCG@5.
- A claimed gain requires a full 500-case run against the frozen baseline.
