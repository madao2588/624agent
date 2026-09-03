"""Deterministic lexical retrieval and context expansion."""

from __future__ import annotations

import re

from aml_memory.analysis import analyze_message
from aml_memory.lexical import lexical_terms
from aml_memory.models import ScoredMessage, StoredMessage
from aml_memory.ports import Embedder, QueryExpander, RetrievalStore
from aml_memory.tags import classify_query

_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
_PROPER_NAME_PATTERN = re.compile(r"\b[A-Z][\w'-]{1,}\b")
_CURRENT_STATE_PATTERN = re.compile(
    r"\b(?:now|current|currently|latest|today|most\s+recent|as\s+of)\b"
    r"|(?:现在|目前|当前|最新|如今)",
    flags=re.IGNORECASE,
)
_HISTORY_STATE_PATTERN = re.compile(
    r"\b(?:history|historical|original|originally|earliest|first|previous|before)\b"
    r"|(?:历史|最初|最早|原来|之前|以前)",
    flags=re.IGNORECASE,
)
_PROMPT_INJECTION_QUERY_PATTERN = re.compile(
    r"\bprompt\s+injection\b|(?:提示词注入|恶意指令)",
    flags=re.IGNORECASE,
)
_CJK_EXPANDED_TERM_PREFIX = re.compile(
    r"^(?:我的|我(?:最近|当前|现在|最新)(?:的|\s*)|"
    r"(?:最近|当前|现在|最新)(?:的|\s+))"
)
_LOW_SIGNAL_EXPANDED_TERMS = frozenset(
    {"current", "latest", "now", "recent", "当前", "最新", "现在", "最近"}
)
_ENGLISH_QUESTION_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "based",
        "be",
        "did",
        "do",
        "does",
        "for",
        "from",
        "go",
        "had",
        "has",
        "have",
        "he",
        "her",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "ours",
        "she",
        "should",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "they",
        "this",
        "to",
        "us",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
    }
)
_CJK_QUESTION_STOPWORDS = frozenset(
    {
        "什么",
        "怎么",
        "如何",
        "哪里",
        "哪个",
        "是否",
        "我的",
        "我和",
        "有什",
        "时候",
    }
)
_LOCAL_QUERY_ALIAS_GROUPS = (
    ("名字", "姓名", "叫什么", "叫", "my name", "name", "named", "called"),
    ("宠物", "狗", "猫", "pet", "dog", "cat"),
    ("咖啡", "coffee"),
    ("住在", "居住", "家住", "城市", "live", "reside", "home", "city"),
    ("工作", "职业", "公司", "job", "work", "occupation", "company"),
    ("同事", "朋友", "家人", "coworker", "colleague", "friend", "family"),
    ("推荐", "建议", "recommend", "suggest"),
    ("习惯", "habit", "routine", "usual", "usually", "always", "often", "总是", "经常"),
    ("偏好", "偏爱", "preference", "prefer", "favorite"),
    ("喜欢", "讨厌", "like", "enjoy", "prefer", "dislike"),
    ("见面", "会议", "计划", "meeting", "meet", "schedule", "plan"),
    ("当前", "最新", "改到", "变更", "current", "latest", "changed", "rescheduled"),
    ("时间", "when", "time", "schedule"),
    ("地点", "哪里", "place", "location", "where"),
    ("步骤", "流程", "必须", "应该", "procedure", "steps", "must", "should"),
    ("周末", "weekend"),
    ("跑步", "run", "running"),
)
_QUERY_FACET_KINDS = frozenset({"entity", "alias", "place", "date", "event"})


def build_fts_query(query: str) -> str | None:
    """Convert untrusted natural language into a safe FTS disjunction."""

    tokens: list[str] = []
    seen: set[str] = set()
    for token in lexical_terms(query):
        if token in _ENGLISH_QUESTION_STOPWORDS or token in _CJK_QUESTION_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    for alias in _expand_local_query_aliases(query, []):
        for token in lexical_terms(alias):
            if token in _ENGLISH_QUESTION_STOPWORDS or token in _CJK_QUESTION_STOPWORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    if not tokens:
        return None
    return " OR ".join(f'"{token}"' for token in tokens)


def _expand_local_query_aliases(query: str, expanded_terms: list[str]) -> list[str]:
    source_text = " ".join((query, *expanded_terms)).casefold()
    source_terms = set(lexical_terms(source_text))
    aliases: list[str] = []
    seen = {term.casefold() for term in expanded_terms}
    for group in _LOCAL_QUERY_ALIAS_GROUPS:
        normalized_group = tuple(alias.casefold() for alias in group)
        if not any(
            alias in source_text or alias in source_terms for alias in normalized_group
        ):
            continue
        for alias in group:
            normalized = alias.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            aliases.append(alias)
    return aliases


def _sanitize_expanded_terms(expanded_terms: list[str]) -> list[str]:
    sanitized: list[str] = []
    seen: set[str] = set()
    for term in expanded_terms:
        candidate = _CJK_EXPANDED_TERM_PREFIX.sub("", term.strip()).strip()
        normalized = candidate.casefold()
        if (
            not candidate
            or normalized in _LOW_SIGNAL_EXPANDED_TERMS
            or normalized in seen
        ):
            continue
        seen.add(normalized)
        sanitized.append(candidate)
    return sanitized


def _is_grounded_lexical_hit(
    query: str,
    message: StoredMessage,
    *,
    base_query: str | None = None,
    strong_terms: tuple[str, ...] = (),
    relevance_threshold: float = 0.0,
) -> bool:
    grounding_query = base_query or query
    query_terms = {
        term
        for term in lexical_terms(grounding_query)
        if term not in _ENGLISH_QUESTION_STOPWORDS
        and term not in _CJK_QUESTION_STOPWORDS
    }
    if not query_terms:
        return False
    content_terms = set(lexical_terms(message.content))
    strong_term_tokens = {
        term for strong_term in strong_terms for term in lexical_terms(strong_term)
    }
    if strong_term_tokens.intersection(content_terms):
        return True
    overlap = query_terms.intersection(content_terms)
    has_required_overlap = len(overlap) >= 2 or (len(query_terms) <= 2 and overlap)
    overlap_ratio = len(overlap) / len(query_terms)
    if has_required_overlap and overlap_ratio >= relevance_threshold:
        return True
    expanded_terms = set(lexical_terms(query)).difference(
        lexical_terms(grounding_query)
    )
    if base_query is not None and expanded_terms.intersection(content_terms):
        return True
    alias_terms = {
        term
        for alias in _expand_local_query_aliases(grounding_query, [])
        for term in lexical_terms(alias)
    }.difference(query_terms)
    return bool(alias_terms.intersection(content_terms))


def _order_lexical_hits(
    hits: list[tuple[StoredMessage, float]],
    *,
    query: str,
) -> list[tuple[StoredMessage, float]]:
    if _is_history_query(query):
        return sorted(
            hits,
            key=lambda item: (
                item[0].occurred_at_ms is None,
                item[0].occurred_at_ms or 0,
                item[0].sequence,
            ),
        )
    if not _is_current_state_query(query):
        return hits
    return sorted(
        hits,
        key=lambda item: (
            item[0].occurred_at_ms is None,
            -(item[0].occurred_at_ms or 0),
            item[1],
            -item[0].sequence,
        ),
    )


def _is_current_state_query(query: str) -> bool:
    return _CURRENT_STATE_PATTERN.search(query) is not None


def _is_history_query(query: str) -> bool:
    return _HISTORY_STATE_PATTERN.search(query) is not None


def _append_reason(reasons: tuple[str, ...], reason: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*reasons, reason)))


def _expand_current_state_chain(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
    top_k: int,
) -> list[ScoredMessage]:
    wants_current = _is_current_state_query(query)
    wants_history = _is_history_query(query)
    if not direct_results or (not wants_current and not wants_history):
        return direct_results
    chain_limit = min(100, max(20, top_k * 4))
    chain_messages = store.list_state_chain(
        user_id=user_id,
        message_ids=[result.message.id for result in direct_results],
        limit=chain_limit,
    )
    messages = {result.message.id: result.message for result in direct_results}
    messages.update({message.id: message for message in chain_messages})
    if wants_history:
        ranked_messages = sorted(
            messages.values(),
            key=lambda message: (
                message.occurred_at_ms is None,
                message.occurred_at_ms or 0,
                message.sequence,
            ),
        )
    else:
        ranked_messages = sorted(
            messages.values(),
            key=lambda message: (
                message.occurred_at_ms is None,
                -(message.occurred_at_ms or 0),
                -message.sequence,
            ),
        )
    direct_by_id = {result.message.id: result for result in direct_results}
    route = "history-chain" if wants_history else "state-chain"
    return [
        ScoredMessage(
            message=message,
            score=1.0 / rank,
            reasons=_append_reason(
                direct_by_id.get(message.id, ScoredMessage(message, 0.0)).reasons,
                route,
            ),
        )
        for rank, message in enumerate(ranked_messages, start=1)
    ]


def _expand_intent_tags(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
    top_k: int,
) -> list[ScoredMessage]:
    intents = classify_query(query)
    if not intents:
        return direct_results
    messages = {result.message.id: result.message for result in direct_results}
    scores = {result.message.id: result.score for result in direct_results}
    reasons = {result.message.id: result.reasons for result in direct_results}
    tag_limit = min(100, max(20, top_k * 4))
    for kind in intents:
        tagged_messages = store.list_tagged_messages(
            user_id=user_id,
            kind=kind,
            limit=tag_limit,
        )
        for rank, message in enumerate(tagged_messages, start=1):
            messages[message.id] = message
            scores[message.id] = scores.get(message.id, 0.0) + (1.25 / rank)
            reasons[message.id] = _append_reason(
                reasons.get(message.id, ()), f"tag:{kind}"
            )
    if not scores:
        return []
    max_score = max(scores.values())
    expanded = [
        ScoredMessage(
            message=messages[message_id],
            score=score / max_score,
            reasons=reasons.get(message_id, ()),
        )
        for message_id, score in scores.items()
    ]
    expanded.sort(key=lambda result: (-result.score, -result.message.sequence))
    return expanded


def _expand_query_facets(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
    top_k: int,
    candidate_limit: int | None = None,
) -> list[ScoredMessage]:
    query_facets = tuple(
        facet
        for facet in analyze_message(query, occurred_at_ms=None).facets
        if facet.kind in _QUERY_FACET_KINDS and facet.confidence >= 0.85
    )
    if not query_facets:
        return direct_results
    messages = {result.message.id: result.message for result in direct_results}
    scores = {result.message.id: result.score for result in direct_results}
    reasons = {result.message.id: result.reasons for result in direct_results}
    facet_hits = store.search_facets(
        user_id=user_id,
        facets=query_facets,
        limit=candidate_limit or min(200, max(20, top_k * 4)),
    )
    for rank, message in enumerate(facet_hits, start=1):
        messages[message.id] = message
        scores[message.id] = scores.get(message.id, 0.0) + (0.85 / rank)
        reasons[message.id] = _append_reason(reasons.get(message.id, ()), "facet")
    if not scores:
        return []
    max_score = max(scores.values())
    expanded = [
        ScoredMessage(
            message=messages[message_id],
            score=score / max_score,
            reasons=reasons.get(message_id, ()),
        )
        for message_id, score in scores.items()
    ]
    expanded.sort(key=lambda result: (-result.score, -result.message.sequence))
    return expanded


def _bridge_terms(
    *,
    query: str,
    direct_results: list[ScoredMessage],
    limit: int = 8,
) -> list[str]:
    query_terms = {
        match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(query)
    }
    terms: list[str] = []
    seen: set[str] = set()
    for result in direct_results[:3]:
        for match in _PROPER_NAME_PATTERN.finditer(result.message.content):
            term = match.group(0)
            normalized = term.casefold()
            if normalized in query_terms or normalized in _ENGLISH_QUESTION_STOPWORDS:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
            if len(terms) == limit:
                return terms
    return terms


def _expand_entity_bridges(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
    top_k: int,
) -> list[ScoredMessage]:
    terms = _bridge_terms(query=query, direct_results=direct_results)
    if not terms:
        return direct_results
    bridge_query = build_fts_query(" ".join(terms))
    if bridge_query is None:
        return direct_results

    selected_ids = {result.message.id for result in direct_results}
    expanded = list(direct_results)
    bridge_limit = min(40, max(10, top_k * 2))
    bridge_hits = store.search_fts(
        user_id=user_id,
        fts_query=bridge_query,
        limit=bridge_limit,
    )
    for rank, (message, _lexical_score) in enumerate(bridge_hits, start=1):
        if message.id in selected_ids:
            continue
        selected_ids.add(message.id)
        expanded.append(
            ScoredMessage(message=message, score=0.5 / rank, reasons=("entity-bridge",))
        )
    return expanded


def _expand_relation_graph(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    user_id: str,
    top_k: int,
    max_hops: int = 3,
) -> list[ScoredMessage]:
    if not direct_results:
        return []
    selected = {result.message.id: result for result in direct_results}
    relation_limit = min(200, max(20, top_k * 4))
    related = store.list_related_messages(
        user_id=user_id,
        message_ids=[result.message.id for result in direct_results],
        max_hops=max_hops,
        limit=relation_limit,
    )
    for item in related:
        selected.setdefault(
            item.message.id,
            ScoredMessage(
                message=item.message,
                score=0.65 / item.hop,
                reasons=(f"graph:{item.hop}:{item.anchor}",),
            ),
        )
    ranked = sorted(
        selected.values(),
        key=lambda result: (-result.score, -result.message.sequence),
    )
    return ranked


def _filter_unsafe_memories(
    store: RetrievalStore,
    results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
) -> list[ScoredMessage]:
    if not results or _PROMPT_INJECTION_QUERY_PATTERN.search(query) is not None:
        return results
    facet_map = store.list_message_facets(
        user_id=user_id,
        message_ids=[result.message.id for result in results],
    )
    unsafe_ids = {
        message_id
        for message_id, facets in facet_map.items()
        if any(
            facet.kind == "safety" and facet.normalized_value == "prompt-injection"
            for facet in facets
        )
    }
    return [result for result in results if result.message.id not in unsafe_ids]


def _filter_forgotten_memories(
    store: RetrievalStore,
    results: list[ScoredMessage],
    *,
    query: str,
    user_id: str,
) -> list[ScoredMessage]:
    if not results or _is_history_query(query):
        return results
    message_ids = [result.message.id for result in results]
    facet_map = store.list_message_facets(user_id=user_id, message_ids=message_ids)
    forget_markers = {
        message_id
        for message_id, facets in facet_map.items()
        if any(
            facet.kind == "event_status" and facet.normalized_value == "forget"
            for facet in facets
        )
    }
    forgotten_ids = store.list_forgotten_message_ids(
        user_id=user_id,
        message_ids=message_ids,
    )
    hidden_ids = forget_markers.union(forgotten_ids)
    return [result for result in results if result.message.id not in hidden_ids]


def _expand_neighbors(
    store: RetrievalStore,
    direct_results: list[ScoredMessage],
    *,
    user_id: str,
    top_k: int,
    neighbor_radius: int,
    query: str,
) -> list[ScoredMessage]:
    selected = {result.message.id: result for result in direct_results}
    intents = classify_query(query)
    if neighbor_radius:
        session_cache: dict[str, list[StoredMessage]] = {}
        for result in direct_results:
            hit = result.message
            session_messages = session_cache.setdefault(
                hit.session_id,
                store.list_session_messages(user_id=user_id, session_id=hit.session_id),
            )
            hit_index = next(
                index for index, message in enumerate(session_messages) if message.id == hit.id
            )
            for distance in range(1, neighbor_radius + 1):
                for neighbor_index in (hit_index - distance, hit_index + distance):
                    if not 0 <= neighbor_index < len(session_messages):
                        continue
                    neighbor = session_messages[neighbor_index]
                    if "preference" in intents:
                        neighbor_facets = store.list_message_facets(
                            user_id=user_id,
                            message_ids=[neighbor.id],
                        ).get(neighbor.id, ())
                        neighbor_kinds = {facet.kind for facet in neighbor_facets}
                        if "one_off" in neighbor_kinds and not neighbor_kinds.intersection(
                            {"habit", "preference", "aversion"}
                        ):
                            continue
                    selected.setdefault(
                        neighbor.id,
                        ScoredMessage(
                            message=neighbor,
                            score=result.score / (distance + 1),
                            reasons=(f"session-neighbor:{distance}",),
                        ),
                    )

    ranked = sorted(
        selected.values(),
        key=lambda result: (-result.score, result.message.sequence),
    )
    return ranked[:top_k]


class LexicalRetrievalPipeline:
    """FTS5 baseline with same-session neighbor expansion."""

    def __init__(
        self,
        store: RetrievalStore,
        *,
        neighbor_radius: int = 1,
        lexical_candidate_limit: int | None = None,
        facet_candidate_limit: int | None = None,
        graph_hops: int = 3,
        relevance_threshold: float = 0.0,
    ) -> None:
        if neighbor_radius < 0:
            raise ValueError("neighbor_radius must not be negative")
        if lexical_candidate_limit is not None and lexical_candidate_limit <= 0:
            raise ValueError("lexical_candidate_limit must be positive")
        if facet_candidate_limit is not None and facet_candidate_limit <= 0:
            raise ValueError("facet_candidate_limit must be positive")
        if not 1 <= graph_hops <= 3:
            raise ValueError("graph_hops must be between 1 and 3")
        if not 0.0 <= relevance_threshold <= 1.0:
            raise ValueError("relevance_threshold must be between 0 and 1")
        self._store = store
        self._neighbor_radius = neighbor_radius
        self._lexical_candidate_limit = lexical_candidate_limit
        self._facet_candidate_limit = facet_candidate_limit
        self._graph_hops = graph_hops
        self._relevance_threshold = relevance_threshold

    def search(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int,
        intent_query: str | None = None,
        strong_terms: tuple[str, ...] = (),
    ) -> list[ScoredMessage]:
        if top_k <= 0:
            return []
        original_query = intent_query or query
        hits: list[tuple[StoredMessage, float]] = []
        fts_query = build_fts_query(query)
        if fts_query is not None:
            hits = self._store.search_fts(
                user_id=user_id,
                fts_query=fts_query,
                limit=self._lexical_candidate_limit or top_k,
            )
        hits = [
            hit
            for hit in hits
            if _is_grounded_lexical_hit(
                query,
                hit[0],
                base_query=original_query,
                strong_terms=strong_terms,
                relevance_threshold=self._relevance_threshold,
            )
        ]
        hits = _order_lexical_hits(hits, query=original_query)
        direct_results = [
            ScoredMessage(message=message, score=1.0 / rank, reasons=("lexical",))
            for rank, (message, _lexical_score) in enumerate(hits, start=1)
        ]
        direct_results = _expand_query_facets(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
            top_k=top_k,
            candidate_limit=self._facet_candidate_limit,
        )
        direct_results = _expand_current_state_chain(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_intent_tags(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_entity_bridges(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_relation_graph(
            self._store,
            direct_results,
            user_id=user_id,
            top_k=top_k,
            max_hops=self._graph_hops,
        )
        direct_results = _filter_forgotten_memories(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
        )
        direct_results = _filter_unsafe_memories(
            self._store,
            direct_results,
            query=original_query,
            user_id=user_id,
        )
        expanded = _expand_neighbors(
            self._store,
            direct_results,
            user_id=user_id,
            top_k=top_k,
            neighbor_radius=self._neighbor_radius,
            query=original_query,
        )
        expanded = _filter_forgotten_memories(
            self._store,
            expanded,
            query=original_query,
            user_id=user_id,
        )
        return _filter_unsafe_memories(
            self._store,
            expanded,
            query=original_query,
            user_id=user_id,
        )[:top_k]


class QueryExpansionRetrievalPipeline:
    """Expand only the query externally, then retrieve memories locally."""

    def __init__(
        self,
        store: RetrievalStore,
        query_expander: QueryExpander,
        *,
        neighbor_radius: int = 1,
        lexical_candidate_limit: int | None = None,
        facet_candidate_limit: int | None = None,
        graph_hops: int = 3,
        relevance_threshold: float = 0.0,
    ) -> None:
        self._query_expander = query_expander
        self._lexical = LexicalRetrievalPipeline(
            store,
            neighbor_radius=neighbor_radius,
            lexical_candidate_limit=lexical_candidate_limit,
            facet_candidate_limit=facet_candidate_limit,
            graph_hops=graph_hops,
            relevance_threshold=relevance_threshold,
        )

    def search(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int,
        strong_terms: tuple[str, ...] = (),
    ) -> list[ScoredMessage]:
        if top_k <= 0:
            return []
        expanded_terms = _sanitize_expanded_terms(self._query_expander.expand(query))
        local_results = self._lexical.search(
            query=query,
            user_id=user_id,
            top_k=top_k,
            intent_query=query,
            strong_terms=strong_terms,
        )
        if not expanded_terms:
            return local_results

        expanded_query = " ".join((query, *expanded_terms))
        expanded_results = self._lexical.search(
            query=expanded_query,
            user_id=user_id,
            top_k=min(400, max(20, top_k * 4)),
            intent_query=query,
            strong_terms=strong_terms,
        )
        tagged_expanded = [
            ScoredMessage(
                message=result.message,
                score=result.score,
                reasons=_append_reason(result.reasons, "model-expanded"),
            )
            for result in expanded_results
        ]
        if not local_results:
            return tagged_expanded[:top_k]

        local_ids = {result.message.id for result in local_results}
        local_sessions = {
            result.message.session_id for result in local_results[: min(10, top_k)]
        }
        bridge_tokens = {
            token
            for term in _bridge_terms(query=query, direct_results=local_results)
            for token in lexical_terms(term)
        }
        connected_expanded = [
            result
            for result in tagged_expanded
            if result.message.id in local_ids
            or result.message.session_id in local_sessions
            or bridge_tokens.intersection(lexical_terms(result.message.content))
        ]
        if {result.message.id for result in connected_expanded}.issubset(local_ids):
            return local_results

        messages = {result.message.id: result.message for result in local_results}
        scores: dict[str, float] = {}
        reasons = {result.message.id: result.reasons for result in local_results}
        for ranking in (local_results, connected_expanded):
            for rank, result in enumerate(ranking, start=1):
                message_id = result.message.id
                messages[message_id] = result.message
                scores[message_id] = scores.get(message_id, 0.0) + (1.0 / (60 + rank))
                reasons[message_id] = tuple(
                    dict.fromkeys((*reasons.get(message_id, ()), *result.reasons))
                )
        max_score = max(scores.values())
        fused = [
            ScoredMessage(
                message=messages[message_id],
                score=score / max_score,
                reasons=reasons[message_id],
            )
            for message_id, score in scores.items()
        ]
        fused.sort(key=lambda result: (-result.score, result.message.sequence))
        return fused[:top_k]


class HybridRetrievalPipeline:
    """Fuse lexical and semantic candidate ranks while returning source messages."""

    def __init__(
        self,
        store: RetrievalStore,
        embedder: Embedder,
        *,
        neighbor_radius: int = 1,
        lexical_candidate_limit: int | None = None,
        vector_candidate_limit: int | None = None,
        minimum_vector_similarity: float = 0.18,
        rrf_k: int = 60,
    ) -> None:
        if neighbor_radius < 0:
            raise ValueError("neighbor_radius must not be negative")
        if lexical_candidate_limit is not None and lexical_candidate_limit <= 0:
            raise ValueError("lexical_candidate_limit must be positive")
        if vector_candidate_limit is not None and vector_candidate_limit <= 0:
            raise ValueError("vector_candidate_limit must be positive")
        if not 0.0 <= minimum_vector_similarity <= 1.0:
            raise ValueError("minimum_vector_similarity must be between 0 and 1")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        self._store = store
        self._embedder = embedder
        self._neighbor_radius = neighbor_radius
        self._lexical_candidate_limit = lexical_candidate_limit
        self._vector_candidate_limit = vector_candidate_limit
        self._minimum_vector_similarity = minimum_vector_similarity
        self._rrf_k = rrf_k

    @staticmethod
    def _default_candidate_limit(top_k: int) -> int:
        return min(400, max(20, top_k * 4))

    def search(
        self,
        *,
        query: str,
        user_id: str,
        top_k: int,
        strong_terms: tuple[str, ...] = (),
    ) -> list[ScoredMessage]:
        if top_k <= 0:
            return []
        default_limit = self._default_candidate_limit(top_k)
        lexical_limit = self._lexical_candidate_limit or default_limit
        vector_limit = self._vector_candidate_limit or default_limit

        lexical_hits: list[tuple[StoredMessage, float]] = []
        fts_query = build_fts_query(query)
        if fts_query is not None:
            lexical_hits = self._store.search_fts(
                user_id=user_id,
                fts_query=fts_query,
                limit=lexical_limit,
            )
        lexical_hits = [
            hit
            for hit in lexical_hits
            if _is_grounded_lexical_hit(query, hit[0], strong_terms=strong_terms)
        ]

        query_batch = self._embedder.embed([query])
        vector_hits = self._store.search_vectors(
            user_id=user_id,
            model=query_batch.model,
            query_vector=query_batch.vectors[0],
            limit=vector_limit,
        )
        vector_hits = [
            hit for hit in vector_hits if hit[1] >= self._minimum_vector_similarity
        ]

        messages: dict[str, StoredMessage] = {}
        fused_scores: dict[str, float] = {}
        fused_reasons: dict[str, tuple[str, ...]] = {}
        for route, ranking in (("lexical", lexical_hits), ("vector", vector_hits)):
            for rank, (message, _source_score) in enumerate(ranking, start=1):
                messages[message.id] = message
                fused_scores[message.id] = fused_scores.get(message.id, 0.0) + (
                    1.0 / (self._rrf_k + rank)
                )
                fused_reasons[message.id] = _append_reason(
                    fused_reasons.get(message.id, ()), route
                )
        direct_results: list[ScoredMessage] = []
        if fused_scores:
            max_score = max(fused_scores.values())
            direct_results = [
                ScoredMessage(
                    message=messages[message_id],
                    score=score / max_score,
                    reasons=fused_reasons.get(message_id, ()),
                )
                for message_id, score in fused_scores.items()
            ]
        direct_results.sort(key=lambda result: (-result.score, result.message.sequence))
        direct_results = _expand_query_facets(
            self._store,
            direct_results,
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_current_state_chain(
            self._store,
            direct_results,
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_intent_tags(
            self._store,
            direct_results,
            query=query,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _expand_relation_graph(
            self._store,
            direct_results,
            user_id=user_id,
            top_k=top_k,
        )
        direct_results = _filter_forgotten_memories(
            self._store,
            direct_results,
            query=query,
            user_id=user_id,
        )
        direct_results = _filter_unsafe_memories(
            self._store,
            direct_results,
            query=query,
            user_id=user_id,
        )
        expanded = _expand_neighbors(
            self._store,
            direct_results,
            user_id=user_id,
            top_k=top_k,
            neighbor_radius=self._neighbor_radius,
            query=query,
        )
        expanded = _filter_forgotten_memories(
            self._store,
            expanded,
            query=query,
            user_id=user_id,
        )
        return _filter_unsafe_memories(
            self._store,
            expanded,
            query=query,
            user_id=user_id,
        )[:top_k]
