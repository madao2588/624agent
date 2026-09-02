from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aml_memory.retrieval import LexicalRetrievalPipeline
from aml_memory.schemas import AddRequest, MessageInput
from aml_memory.store import MemoryStore


def test_concurrent_identical_adds_create_one_copy(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    request = AddRequest(
        request_id="concurrent-request",
        user_id="user-1",
        session_id="session-1",
        messages=[MessageInput(role="user", content="One durable memory.")],
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _index: store.add(request), range(32)))

    assert sum(result.inserted for result in results) == 1
    assert {result.message_ids for result in results} == {results[0].message_ids}
    assert store.count_messages() == 1


def test_64_distinct_adds_and_256_searches_remain_available(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.initialize()
    requests = [
        AddRequest(
            request_id=f"parallel-{index}",
            user_id="user-1",
            session_id=f"parallel-{index}",
            messages=[
                MessageInput(role="user", content=f"Parallel marker MEMORY{index}.")
            ],
        )
        for index in range(64)
    ]

    with ThreadPoolExecutor(max_workers=64) as executor:
        inserted = list(executor.map(store.add, requests))

    retrieval = LexicalRetrievalPipeline(store, neighbor_radius=0)
    with ThreadPoolExecutor(max_workers=256) as executor:
        results = list(
            executor.map(
                lambda index: retrieval.search(
                    query=f"Parallel marker MEMORY{index % 64}",
                    user_id="user-1",
                    top_k=1,
                ),
                range(256),
            )
        )

    assert all(result.inserted for result in inserted)
    assert store.count_messages() == 64
    assert all(result for result in results)
