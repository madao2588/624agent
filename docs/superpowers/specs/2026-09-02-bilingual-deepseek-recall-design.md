# Bilingual DeepSeek Recall Design

## Goal

Make the existing DeepSeek query-assistant path visibly useful for one person's
multi-turn memory, especially when the question and stored memory use different
languages. Keep the established privacy boundary: DeepSeek receives the search
question, but never receives stored memories, user IDs, or retrieved evidence.

## Chosen approach

Use retrieval-oriented bilingual query expansion, then keep the existing local
BM25, state-chain, tag, entity-bridge, and neighbor retrieval stages.

The DeepSeek instruction must require:

- short phrases likely to occur verbatim in a stored memory;
- both Chinese and English variants when the query is Chinese or English;
- stable personal-memory anchors for identity, names, preferences, places,
  relationships, plans, procedures, negation, and time changes;
- no guessed personal answer and no memory text.

The original query remains part of the local search, so exact matches continue
to work even when expansion quality is poor.

## Alternatives considered

1. Send all stored memories to DeepSeek and ask it to select evidence. This
   would improve semantic matching, but changes the privacy contract and grows
   request cost and latency with memory size. It is not authorized in this pass.
2. Require a separate embedding API. This is genuine vector retrieval and the
   project already supports it, but it requires another compatible provider and
   key. It cannot make the user's current DeepSeek-only setup work by itself.

## Visible behavior

- A successful search reports the actual evidence count and identifies DeepSeek
  bilingual expansion when that connection is active.
- A zero-hit search is neutral and explicit; it must never say evidence was
  found.
- Settings copy describes the mode as bilingual query expansion, not vector
  retrieval or an answer-generating model.

## Verification

Offline deterministic tests cover Chinese-to-English and English-to-Chinese
identity, preference, relation, plan-update, negation/procedure, zero-hit, and
user-isolation cases. Provider request tests verify the bilingual instruction
and the query-only privacy boundary. Browser verification checks both positive
and zero-result status messages.
