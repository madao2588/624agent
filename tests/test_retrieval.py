# ruff: noqa: RUF001 - natural Chinese memories keep native punctuation

from pathlib import Path

import pytest

from aml_memory.formatting import format_evidence
from aml_memory.models import EmbeddingBatch
from aml_memory.retrieval import (
    HybridRetrievalPipeline,
    LexicalRetrievalPipeline,
    QueryExpansionRetrievalPipeline,
)
from aml_memory.schemas import AddRequest, MessageInput
from aml_memory.store import MemoryStore


class FakeEmbedder:
    model = "semantic-test"

    def __init__(self, vectors: dict[str, tuple[float, ...]]) -> None:
        self._vectors = vectors

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            model=self.model,
            vectors=tuple(self._vectors[text] for text in texts),
        )


class FakeQueryExpander:
    def __init__(self, terms: list[str]) -> None:
        self.terms = terms
        self.calls: list[str] = []

    def expand(self, query: str) -> list[str]:
        self.calls.append(query)
        return self.terms


def test_query_expansion_pipeline_applies_frozen_candidate_and_graph_limits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-profile-limits",
        user_id="user-1",
        session_id="session-1",
        messages=[MessageInput(role="user", content="Nimbus review meeting")],
    )
    fts_limits: list[int] = []
    facet_limits: list[int] = []
    graph_hops: list[int] = []
    original_search_fts = store.search_fts
    original_search_facets = store.search_facets
    original_list_related = store.list_related_messages

    def search_fts(*, user_id: str, fts_query: str, limit: int):
        fts_limits.append(limit)
        return original_search_fts(user_id=user_id, fts_query=fts_query, limit=limit)

    def search_facets(*, user_id: str, facets, limit: int):
        facet_limits.append(limit)
        return original_search_facets(user_id=user_id, facets=facets, limit=limit)

    def list_related_messages(
        *,
        user_id: str,
        message_ids: list[str],
        max_hops: int,
        limit: int,
    ):
        graph_hops.append(max_hops)
        return original_list_related(
            user_id=user_id,
            message_ids=message_ids,
            max_hops=max_hops,
            limit=limit,
        )

    monkeypatch.setattr(store, "search_fts", search_fts)
    monkeypatch.setattr(store, "search_facets", search_facets)
    monkeypatch.setattr(store, "list_related_messages", list_related_messages)
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        FakeQueryExpander([]),
        neighbor_radius=0,
        lexical_candidate_limit=11,
        facet_candidate_limit=7,
        graph_hops=2,
        relevance_threshold=0.18,
    )

    results = retrieval.search(query="Nimbus", user_id="user-1", top_k=3)

    assert results
    assert fts_limits == [11]
    assert facet_limits == [7]
    assert graph_hops == [2]


def test_evaluation_relevance_threshold_rejects_weak_long_query_overlap(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-profile-threshold",
        user_id="user-1",
        session_id="session-1",
        messages=[MessageInput(role="user", content="atlas review happened yesterday.")],
    )
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        FakeQueryExpander([]),
        neighbor_radius=0,
        relevance_threshold=0.75,
    )

    results = retrieval.search(
        query="atlas review medication vehicle ocean",
        user_id="user-1",
        top_k=3,
    )

    assert results == []


def test_query_expansion_retrieves_paraphrased_memory_locally(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-hobby",
        user_id="user-1",
        session_id="session-hobby",
        messages=[
            MessageInput(
                role="user",
                content="Weekends are reserved for cycling outside the city.",
            )
        ],
    )
    expander = FakeQueryExpander(["cycling", "bike rides"])
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="Which outdoor hobby do I enjoy?",
        user_id="user-1",
        top_k=3,
    )

    assert expander.calls == ["Which outdoor hobby do I enjoy?"]
    assert [result.message.content for result in results] == [
        "Weekends are reserved for cycling outside the city."
    ]
    assert results[0].reasons == ("lexical", "model-expanded")


def test_query_expansion_adds_connected_evidence_when_local_search_is_partial(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    overview = "My bicycle needs maintenance before spring."
    detail = "Replace the worn brake pads next week."
    add_session(
        store,
        request_id="request-maintenance",
        user_id="user-1",
        session_id="session-maintenance",
        messages=[
            MessageInput(role="user", content=overview),
            MessageInput(role="assistant", content=detail),
        ],
    )
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        FakeQueryExpander(["brake pads", "replace"]),
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="What bicycle maintenance is pending?",
        user_id="user-1",
        top_k=3,
    )

    assert [result.message.content for result in results] == [overview, detail]
    assert results[1].reasons == ("lexical", "model-expanded")


@pytest.mark.parametrize(
    ("query", "content", "expanded_terms"),
    [
        (
            "我的名字是什么？",
            "My name is Peter Park.",
            ["name", "named", "called", "名字", "姓名", "叫"],
        ),
        (
            "Which city do I live in?",
            "我现在住在苏州。",
            ["live", "city", "home", "住在", "居住", "城市"],
        ),
        (
            "我偏爱什么样的餐厅环境？",
            "I dislike crowded venues and prefer quiet corner tables.",
            ["prefer", "quiet", "crowded", "偏爱", "安静", "拥挤"],
        ),
        (
            "What did my coworker recommend?",
            "同事小林推荐我去玄武湖跑步。",
            ["coworker", "recommend", "同事", "推荐"],
        ),
        (
            "更改已关闭工单前应该怎么做？",
            "Restore frozen tickets before editing them; never modify them in place.",
            ["restore", "before editing", "never modify", "恢复", "修改前", "不得"],
        ),
    ],
    ids=[
        "chinese-query-english-identity",
        "english-query-chinese-place",
        "chinese-query-english-preference",
        "english-query-chinese-relation",
        "chinese-query-english-procedure",
    ],
)
def test_query_expansion_retrieves_bilingual_personal_memories(
    tmp_path: Path,
    query: str,
    content: str,
    expanded_terms: list[str],
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-bilingual",
        user_id="user-1",
        session_id="session-bilingual",
        messages=[MessageInput(role="user", content=content)],
    )
    expander = FakeQueryExpander(expanded_terms)
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(query=query, user_id="user-1", top_k=3)

    assert expander.calls == [query]
    assert [result.message.content for result in results] == [content]


def test_query_expansion_recalls_english_name_from_a_chinese_question(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-name",
        user_id="user-1",
        session_id="session-name",
        messages=[MessageInput(role="user", content="My name is Peter Park.")],
    )
    expander = FakeQueryExpander([])
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="我的名字是什么？",
        user_id="user-1",
        top_k=3,
    )

    assert expander.calls == ["我的名字是什么？"]
    assert [result.message.content for result in results] == ["My name is Peter Park."]


def test_query_expansion_recalls_chinese_running_place_from_an_english_question(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-running",
        user_id="user-1",
        session_id="session-running",
        messages=[MessageInput(role="user", content="新的跑步地点：玄武湖。那里更安静。")],
    )
    expander = FakeQueryExpander([])
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="Where do I run on weekends now?",
        user_id="user-1",
        top_k=3,
    )

    assert expander.calls == ["Where do I run on weekends now?"]
    assert [result.message.content for result in results] == ["新的跑步地点：玄武湖。那里更安静。"]


@pytest.mark.parametrize(
    ("query", "content"),
    [
        ("Which city do I live in?", "我现在居住在苏州。"),
        ("我的宠物叫什么？", "My dog is named Juniper."),
        ("我当前的会议计划是什么？", "The meeting was rescheduled to Friday."),
        ("What procedure should I follow?", "修改工单前必须先恢复它。"),
    ],
    ids=[
        "english-location-to-chinese-memory",
        "chinese-pet-to-english-memory",
        "chinese-current-plan-to-english-memory",
        "english-procedure-to-chinese-memory",
    ],
)
def test_query_expansion_has_local_bilingual_anchors_when_model_terms_are_empty(
    tmp_path: Path,
    query: str,
    content: str,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-local-anchor",
        user_id="user-1",
        session_id="session-local-anchor",
        messages=[MessageInput(role="user", content=content)],
    )
    expander = FakeQueryExpander([])
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(query=query, user_id="user-1", top_k=3)

    assert expander.calls == [query]
    assert [result.message.content for result in results] == [content]


def test_query_expansion_does_not_turn_model_terms_into_user_intent(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    meeting = "The project meeting moved to Friday afternoon."
    preference = "I always choose quiet corner tables and avoid loud rooms."
    add_session(
        store,
        request_id="request-meeting-intent",
        user_id="user-1",
        session_id="session-meeting-intent",
        messages=[MessageInput(role="user", content=meeting)],
    )
    add_session(
        store,
        request_id="request-preference-intent",
        user_id="user-1",
        session_id="session-preference-intent",
        messages=[MessageInput(role="user", content=preference)],
    )
    expander = FakeQueryExpander(["meeting", "schedule", "quiet", "taste"])
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        expander,
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="What is my latest meeting schedule?",
        user_id="user-1",
        top_k=5,
    )

    assert [result.message.content for result in results] == [meeting]


def test_query_expansion_strips_noisy_personal_prefixes_from_model_terms(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    meeting = "计划改了，会议改到周五下午。"
    coffee = "我最近开始只喝燕麦奶拿铁。"
    add_session(
        store,
        request_id="request-noisy-meeting",
        user_id="user-1",
        session_id="session-noisy-meeting",
        messages=[MessageInput(role="user", content=meeting)],
    )
    add_session(
        store,
        request_id="request-noisy-coffee",
        user_id="user-1",
        session_id="session-noisy-coffee",
        messages=[MessageInput(role="user", content=coffee)],
    )
    retrieval = QueryExpansionRetrievalPipeline(
        store,
        FakeQueryExpander(["我最近的会议安排", "最近 会议安排"]),
        neighbor_radius=0,
    )

    results = retrieval.search(
        query="What is my latest meeting schedule?",
        user_id="user-1",
        top_k=5,
    )

    assert [result.message.content for result in results] == [meeting]


def add_session(
    store: MemoryStore,
    *,
    request_id: str,
    user_id: str,
    session_id: str,
    messages: list[MessageInput],
) -> None:
    store.add(
        AddRequest(
            request_id=request_id,
            user_id=user_id,
            session_id=session_id,
            messages=messages,
        )
    )


def test_lexical_retrieval_returns_only_requested_users_evidence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-a",
        user_id="user-a",
        session_id="session-a",
        messages=[MessageInput(role="user", content="My cat is named Luna.")],
    )
    add_session(
        store,
        request_id="request-b",
        user_id="user-b",
        session_id="session-b",
        messages=[MessageInput(role="user", content="Luna is user B's private project name.")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(query="What is Luna?", user_id="user-a", top_k=100)

    assert [result.message.content for result in results] == ["My cat is named Luna."]
    assert {result.message.user_id for result in results} == {"user-a"}


def test_special_fts_syntax_is_treated_as_untrusted_text(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-1",
        user_id="user-1",
        session_id="session-1",
        messages=[MessageInput(role="user", content="I prefer green tea.")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query='green" OR (tea*) NOT secret:-', user_id="user-1", top_k=100
    )

    assert results
    assert results[0].message.content == "I prefer green tea."


def test_question_stopwords_do_not_create_unrelated_evidence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-weather",
        user_id="user-1",
        session_id="session-weather",
        messages=[MessageInput(role="user", content="The rain stopped yesterday.")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="What is the color of my car?",
        user_id="user-1",
        top_k=10,
    )

    assert results == []


def test_current_state_query_prefers_the_newest_matching_source_time(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-old-plan",
        user_id="user-1",
        session_id="session-old-plan",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_067_200_000,
                content="The project meeting is on Monday at 09:00.",
            )
        ],
    )
    add_session(
        store,
        request_id="request-new-plan",
        user_id="user-1",
        session_id="session-new-plan",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_153_600_000,
                content="The project meeting moved to Friday at 14:00.",
            )
        ],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="When is the project meeting now?",
        user_id="user-1",
        top_k=2,
    )

    assert [result.message.content for result in results] == [
        "The project meeting moved to Friday at 14:00.",
        "The project meeting is on Monday at 09:00.",
    ]


def test_chinese_natural_question_retrieves_an_unsegmented_updated_plan(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-old-meeting",
        user_id="user-1",
        session_id="session-old-meeting",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_787_560_800_000,
                content="下周三下午三点和林老师在西湖边见面, 记得带蓝色项目本。",
            )
        ],
    )
    add_session(
        store,
        request_id="request-new-meeting",
        user_id="user-1",
        session_id="session-new-meeting",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_787_733_600_000,
                content="计划改了, 和林老师的见面改到周四上午十点, 地点不变。",
            )
        ],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="我和林老师最新什么时候见?",
        user_id="user-1",
        top_k=2,
    )

    assert [result.message.content for result in results] == [
        "计划改了, 和林老师的见面改到周四上午十点, 地点不变。",
        "下周三下午三点和林老师在西湖边见面, 记得带蓝色项目本。",
    ]


def test_lexical_retrieval_recalls_chinese_running_place_from_english_question(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-cross-running",
        user_id="user-1",
        session_id="session-cross-running",
        messages=[MessageInput(role="user", content="新的跑步地点：玄武湖。那里更安静。")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="Where do I run on weekends now?",
        user_id="user-1",
        top_k=3,
    )

    assert [result.message.content for result in results] == ["新的跑步地点：玄武湖。那里更安静。"]


def test_current_query_expands_a_persisted_state_chain_when_only_old_text_matches(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-old-briefing",
        user_id="user-1",
        session_id="session-old-briefing",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_067_200_000,
                content="The Atlas launch briefing is Friday morning in Room 8.",
            )
        ],
    )
    add_session(
        store,
        request_id="request-new-briefing",
        user_id="user-1",
        session_id="session-new-briefing",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_153_600_000,
                content=(
                    "The Atlas briefing has been rescheduled to Monday afternoon "
                    "in Room 12."
                ),
            )
        ],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="What is the current launch schedule?",
        user_id="user-1",
        top_k=2,
    )

    assert [result.message.content for result in results] == [
        "The Atlas briefing has been rescheduled to Monday afternoon in Room 12.",
        "The Atlas launch briefing is Friday morning in Room 8.",
    ]


def test_entity_bridge_adds_cross_session_relation_evidence(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-colleague",
        user_id="user-1",
        session_id="session-colleague",
        messages=[
            MessageInput(
                role="user",
                content="Maya works alongside Omar on the Atlas project.",
            )
        ],
    )
    add_session(
        store,
        request_id="request-cafe",
        user_id="user-1",
        session_id="session-cafe",
        messages=[
            MessageInput(
                role="user",
                content="Omar recommended Juniper Cafe after visiting it twice.",
            )
        ],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="Where should Maya go based on her coworker's suggestion?",
        user_id="user-1",
        top_k=3,
    )

    assert {result.message.content for result in results} == {
        "Maya works alongside Omar on the Atlas project.",
        "Omar recommended Juniper Cafe after visiting it twice.",
    }


def test_preference_intent_recalls_explicit_evidence_without_shared_words(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    preference = "I always choose quiet corner tables and avoid loud rooms."
    add_session(
        store,
        request_id="request-preference-signal",
        user_id="user-1",
        session_id="session-preference-signal",
        messages=[MessageInput(role="user", content=preference)],
    )
    add_session(
        store,
        request_id="request-preference-distractor",
        user_id="user-1",
        session_id="session-preference-distractor",
        messages=[MessageInput(role="user", content="A parcel arrived at noon.")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)

    results = retrieval.search(
        query="Which dining atmosphere is favored?",
        user_id="user-1",
        top_k=1,
    )

    assert [result.message.content for result in results] == [preference]


def test_neighbor_expansion_stays_in_same_user_and_session(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-1",
        user_id="user-1",
        session_id="session-1",
        messages=[
            MessageInput(role="user", content="My sister recently got married."),
            MessageInput(role="assistant", content="Where was the wedding?"),
            MessageInput(role="user", content="The wedding was in Suzhou."),
        ],
    )
    add_session(
        store,
        request_id="request-2",
        user_id="user-1",
        session_id="session-2",
        messages=[MessageInput(role="user", content="Unrelated Suzhou travel note.")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=1)

    results = retrieval.search(query="wedding location", user_id="user-1", top_k=3)

    contents = [result.message.content for result in results]
    assert "The wedding was in Suzhou." in contents
    assert "Where was the wedding?" in contents
    assert "Unrelated Suzhou travel note." not in contents
    assert len(contents) <= 3


def test_high_value_neighbor_can_replace_lower_ranked_direct_hit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-context",
        user_id="user-1",
        session_id="session-context",
        messages=[
            MessageInput(role="user", content="The answer is Kyoto."),
            MessageInput(role="assistant", content="anchor clue"),
        ],
    )
    add_session(
        store,
        request_id="request-distractor",
        user_id="user-1",
        session_id="session-distractor",
        messages=[MessageInput(role="user", content="anchor clue distractor")],
    )
    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=1)

    results = retrieval.search(query="anchor clue", user_id="user-1", top_k=2)

    contents = [result.message.content for result in results]
    assert contents == ["anchor clue", "The answer is Kyoto."]


def test_evidence_format_keeps_timestamp_role_and_original_content(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    add_session(
        store,
        request_id="request-1",
        user_id="user-1",
        session_id="session-1",
        messages=[
            MessageInput(
                role="user",
                timestamp=1_704_067_200_000,
                content="  preserve exact spacing  ",
            )
        ],
    )
    message = store.list_messages(user_id="user-1")[0]

    evidence = format_evidence(message, score=0.75)

    assert evidence.id == message.id
    assert evidence.content == "[2024-01-01T00:00:00Z] USER:   preserve exact spacing  "
    assert evidence.score == 0.75
    assert evidence.created_at == message.created_at


def test_hybrid_retrieval_finds_a_semantic_paraphrase_without_shared_words(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    memory = "I spend free weekends cycling outside the city."
    distractor = "The quarterly finance report is ready."
    query = "Which outdoor activity does the person enjoy in spare time?"
    store.add(
        AddRequest(
            request_id="request-semantic",
            user_id="user-1",
            session_id="session-1",
            messages=[
                MessageInput(role="user", content=memory),
                MessageInput(role="assistant", content=distractor),
            ],
        ),
        embeddings=EmbeddingBatch(
            model="semantic-test",
            vectors=((1.0, 0.0), (0.0, 1.0)),
        ),
    )
    embedder = FakeEmbedder({query: (1.0, 0.0)})
    retrieval = HybridRetrievalPipeline(store, embedder, neighbor_radius=0)

    results = retrieval.search(query=query, user_id="user-1", top_k=1)

    assert [result.message.content for result in results] == [memory]


def test_rrf_prioritizes_a_candidate_found_by_both_retrievers(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    messages = [
        MessageInput(role="user", content="shared exact exact only"),
        MessageInput(role="user", content="shared overlap"),
        MessageInput(role="user", content="semantic only"),
    ]
    store.add(
        AddRequest(
            request_id="request-rrf",
            user_id="user-1",
            session_id="session-1",
            messages=messages,
        ),
        embeddings=EmbeddingBatch(
            model="semantic-test",
            vectors=((0.0, 1.0), (0.9, 0.1), (1.0, 0.0)),
        ),
    )
    query = "shared exact"
    embedder = FakeEmbedder({query: (1.0, 0.0)})
    retrieval = HybridRetrievalPipeline(
        store,
        embedder,
        neighbor_radius=0,
        lexical_candidate_limit=2,
        vector_candidate_limit=2,
    )

    results = retrieval.search(query=query, user_id="user-1", top_k=3)

    assert results[0].message.content == "shared overlap"


def test_hybrid_vector_path_never_returns_another_users_message(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    for suffix, vector in (("a", (0.8, 0.2)), ("b", (1.0, 0.0))):
        store.add(
            AddRequest(
                request_id=f"request-{suffix}",
                user_id=f"user-{suffix}",
                session_id=f"session-{suffix}",
                messages=[
                    MessageInput(role="user", content=f"private semantic note {suffix}")
                ],
            ),
            embeddings=EmbeddingBatch(
                model="semantic-test",
                vectors=(vector,),
            ),
        )
    query = "unrelated paraphrase"
    retrieval = HybridRetrievalPipeline(
        store,
        FakeEmbedder({query: (1.0, 0.0)}),
        neighbor_radius=0,
    )

    results = retrieval.search(query=query, user_id="user-a", top_k=10)

    assert results
    assert {result.message.user_id for result in results} == {"user-a"}


def test_hybrid_retrieval_drops_low_similarity_vector_noise(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    store.add(
        AddRequest(
            request_id="request-vector-noise",
            user_id="user-1",
            session_id="session-vector-noise",
            messages=[MessageInput(role="user", content="Quarterly tax filing notes.")],
        ),
        embeddings=EmbeddingBatch(model="semantic-test", vectors=((0.0, 1.0),)),
    )
    query = "What is my favorite hiking trail?"
    retrieval = HybridRetrievalPipeline(
        store,
        FakeEmbedder({query: (1.0, 0.0)}),
        neighbor_radius=0,
    )

    assert retrieval.search(query=query, user_id="user-1", top_k=10) == []


def test_hybrid_current_query_also_prefers_the_linked_replacement(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    old_content = "The Atlas launch briefing is Friday morning in Room 8."
    new_content = (
        "The Atlas briefing has been rescheduled to Monday afternoon in Room 12."
    )
    store.add(
        AddRequest(
            request_id="request-old-hybrid-state",
            user_id="user-1",
            session_id="session-old-hybrid-state",
            messages=[
                MessageInput(
                    role="user",
                    timestamp=1_704_067_200_000,
                    content=old_content,
                )
            ],
        ),
        embeddings=EmbeddingBatch(model="semantic-test", vectors=((1.0, 0.0),)),
    )
    store.add(
        AddRequest(
            request_id="request-new-hybrid-state",
            user_id="user-1",
            session_id="session-new-hybrid-state",
            messages=[
                MessageInput(
                    role="user",
                    timestamp=1_704_153_600_000,
                    content=new_content,
                )
            ],
        ),
        embeddings=EmbeddingBatch(model="semantic-test", vectors=((0.0, 1.0),)),
    )
    query = "What is the current launch schedule?"
    retrieval = HybridRetrievalPipeline(
        store,
        FakeEmbedder({query: (1.0, 0.0)}),
        neighbor_radius=0,
    )

    results = retrieval.search(query=query, user_id="user-1", top_k=2)

    assert [result.message.content for result in results] == [new_content, old_content]


def test_hybrid_procedure_intent_boosts_the_tagged_source(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    procedure = (
        "Restore frozen tickets before editing them; never modify them in place."
    )
    distractor = "The quarterly finance report is ready."
    store.add(
        AddRequest(
            request_id="request-hybrid-procedure",
            user_id="user-1",
            session_id="session-hybrid-procedure",
            messages=[
                MessageInput(role="assistant", content=procedure),
                MessageInput(role="user", content=distractor),
            ],
        ),
        embeddings=EmbeddingBatch(
            model="semantic-test",
            vectors=((0.0, 1.0), (1.0, 0.0)),
        ),
    )
    query = "What is the required procedure for altering closed support cases?"
    retrieval = HybridRetrievalPipeline(
        store,
        FakeEmbedder({query: (1.0, 0.0)}),
        neighbor_radius=0,
    )

    results = retrieval.search(query=query, user_id="user-1", top_k=1)

    assert [result.message.content for result in results] == [procedure]
