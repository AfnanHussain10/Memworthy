"""TypeSafe Jev judge: the System One preset for https://api.typesafe.ai."""

from __future__ import annotations

import os

import httpx

from memworthy.judges.base import JudgeError
from memworthy.judges.systemone import SystemOneJudge, build_request, parse_response

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-1.13.0"

__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL", "JevJudge", "build_request", "parse_response"]


class JevJudge(SystemOneJudge):
    """Judge backed by TypeSafe's Jev model. One POST per candidate."""

    name = "jev"
    label = "Jev"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure from arguments, falling back to TYPESAFE_* and MEMWORTHY_MODEL env vars."""
        key = api_key or os.environ.get("TYPESAFE_API_KEY") or ""
        if not key:
            raise JudgeError("TYPESAFE_API_KEY is not set; pass api_key or use MockJudge")
        super().__init__(
            api_key=key,
            base_url=base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL,
            model=model or os.environ.get("MEMWORTHY_MODEL") or DEFAULT_MODEL,
            timeout=timeout, retries=retries, backoff=backoff, client=client)
