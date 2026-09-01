from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_memory.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(database_path=tmp_path / "memory.db", neighbor_radius=1)
    with TestClient(app) as test_client:
        yield test_client
