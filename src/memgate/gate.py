"""Public entry point: ``Gate``."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Literal, TypeVar

from memgate.engine import Engine
from memgate.judges.base import Judge
from memgate.ledger import JsonlLedger, Ledger
from memgate.models import Candidate, Decision, Episode
from memgate.policy.loader import Policy, load_policy
from memgate.policy.schema import PolicySpec
from memgate.stores.base import MemoryStore

T = TypeVar("T")
Extractor = Any  # Callable[[Episode], Awaitable[list[Candidate]]]
SessionFormat = Literal["claude_code", "codex", "auto"]


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine from sync code; refuse inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    raise RuntimeError("an event loop is running; use the async a* methods instead")


class Gate:
    """Gates candidate memories through a policy, a judge and a store."""

    def __init__(
        self,
        policy: str | Path | PolicySpec | Policy,
        store: MemoryStore,
        judge: Judge | None = None,
        ledger: Ledger | None = None,
        extractor: Extractor | None = None,
        apply: bool = True,
        concurrency: int = 8,
    ) -> None:
        """Load the policy; default judge is JevJudge from env, default ledger is JSONL."""
        self.policy = load_policy(policy)
        self.store = store
        if judge is None:
            from memgate.judges.jev import JevJudge

            judge = JevJudge()
        self.judge = judge
        self.ledger: Ledger = ledger if ledger is not None else JsonlLedger()
        self.extractor = extractor
        self.apply = apply
        self.concurrency = max(1, concurrency)
        self.engine = Engine(self.policy, store, judge, self.ledger, apply=apply)

    async def aevaluate(self, candidates: list[Candidate]) -> list[Decision]:
        """Decide every candidate; same-subject candidates run in order."""
        sem = asyncio.Semaphore(self.concurrency)
        results: list[Decision | None] = [None] * len(candidates)
        groups: dict[str, list[int]] = {}
        for i, c in enumerate(candidates):
            groups.setdefault(c.subject, []).append(i)

        async def run_group(indices: list[int]) -> None:
            for i in indices:
                async with sem:
                    results[i] = await self.engine.decide(candidates[i])

        await asyncio.gather(*(run_group(ix) for ix in groups.values()))
        return [d for d in results if d is not None]

    def evaluate(self, candidates: list[Candidate]) -> list[Decision]:
        """Sync wrapper for :meth:`aevaluate`."""
        return run_sync(self.aevaluate(candidates))

    async def aingest_messages(self, messages: list[dict[str, Any]]) -> list[Decision]:
        """Gate chat messages (one candidate per user message, or the extractor's output)."""
        from memgate.sources.chat import candidates_from_messages

        return await self.aevaluate(await candidates_from_messages(messages, self.extractor))

    def ingest_messages(self, messages: list[dict[str, Any]]) -> list[Decision]:
        """Sync wrapper for :meth:`aingest_messages`."""
        return run_sync(self.aingest_messages(messages))

    async def aingest_sessions(self, path: str | Path,
                               fmt: SessionFormat = "auto") -> list[Decision]:
        """Parse sessions, split episodes, drop noise, extract and gate candidates."""
        from memgate.sources.pipeline import session_candidates

        cands = await session_candidates(self.policy, self.judge, path, fmt, self.extractor)
        return await self.aevaluate(cands)

    def ingest_sessions(self, path: str | Path, fmt: SessionFormat = "auto") -> list[Decision]:
        """Sync wrapper for :meth:`aingest_sessions`."""
        return run_sync(self.aingest_sessions(path, fmt))


__all__ = ["Episode", "Gate", "run_sync"]
