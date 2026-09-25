"""Session pipeline: parse, split into episodes, drop noise, extract candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memgate.judges.base import Judge
from memgate.models import Candidate
from memgate.policy.loader import Policy


async def session_candidates(policy: Policy, judge: Judge, path: str | Path, fmt: str,
                             extractor: Any = None) -> list[Candidate]:
    """Candidates from a folder of coding-agent sessions (implemented in milestone 3)."""
    raise NotImplementedError("session ingestion arrives in milestone 3")
