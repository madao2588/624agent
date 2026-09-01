from pathlib import Path

from aml_memory.formatting import format_evidence
from aml_memory.retrieval import LexicalRetrievalPipeline
from aml_memory.schemas import AddRequest, MessageInput
from aml_memory.store import MemoryStore


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
