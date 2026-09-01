from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
