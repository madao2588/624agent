"""Optional evaluation API authentication without secret disclosure."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from aml_memory.config import Settings

_AUTH_FAILURE = {"reason": "invalid or missing API credential"}


class ApiKeyAuthenticator:
    """FastAPI dependency implementing the schemes accepted by the leaderboard."""

    def __init__(self, settings: Settings) -> None:
        self._scheme = settings.auth_scheme
        self._api_key = settings.api_key

    def __call__(
        self,
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ) -> None:
        if self._scheme == "none":
            return

        provided: str | None = None
        if self._scheme == "x-api-key":
            provided = x_api_key
        elif authorization is not None:
            prefix, separator, credential = authorization.partition(" ")
            if separator and prefix.casefold() == self._scheme.casefold():
                provided = credential

        expected = self._api_key
        if provided is None or expected is None or not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail=_AUTH_FAILURE)
