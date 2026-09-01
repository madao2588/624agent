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
    auth_scheme: str = "none"
    api_key: str | None = None

    def __post_init__(self) -> None:
        scheme = self.auth_scheme.strip().lower()
        if scheme not in {"none", "token", "bearer", "x-api-key"}:
            raise ValueError("MEMORY_AUTH_SCHEME must be none, token, bearer, or x-api-key")
        object.__setattr__(self, "auth_scheme", scheme)

        has_key = self.api_key is not None and bool(self.api_key.strip())
        if scheme == "none" and has_key:
            raise ValueError("MEMORY_API_KEY requires an enabled MEMORY_AUTH_SCHEME")
        if scheme != "none" and not has_key:
            raise ValueError("MEMORY_API_KEY is required when API authentication is enabled")

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            database_path=Path(os.getenv("MEMORY_DB_PATH", "data/memory.db")),
            neighbor_radius=int(os.getenv("MEMORY_NEIGHBOR_RADIUS", "1")),
            auth_scheme=os.getenv("MEMORY_AUTH_SCHEME", "none"),
            api_key=os.getenv("MEMORY_API_KEY") or None,
        )
