"""Runtime configuration for the memory service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings with deterministic local defaults."""

    database_path: Path
    neighbor_radius: int = 1

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_path=Path(os.getenv("MEMORY_DB_PATH", "data/memory.db")),
            neighbor_radius=int(os.getenv("MEMORY_NEIGHBOR_RADIUS", "1")),
        )
