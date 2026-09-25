"""In-memory store used by tests and the playground."""

from __future__ import annotations

from memgate.models import Candidate, Decision, Memory
from memgate.stores.base import (
    StoreError,
    archived,
    merged_memory,
    new_memory,
    superseding_memory,
    updated_memory,
)
from memgate.stores.rank import bm25_rank


class DictStore:
    """Keeps memories in a dict; superseded memories move to ``archive``."""

    def __init__(self, memories: list[Memory] | None = None) -> None:
        """Start with optional existing memories."""
        self.memories: dict[str, Memory] = {m.id: m for m in memories or []}
        self.archive: dict[str, Memory] = {}

    async def similar(self, candidate: Candidate, k: int) -> list[Memory]:
        """BM25 over memories of the same subject, querying text plus context."""
        pool = [m for m in self.memories.values() if m.subject == candidate.subject]
        query = f"{candidate.text}\n{candidate.context}"
        return [pool[i] for i, _ in bm25_rank(query, [m.text for m in pool], k)]

    async def all(self, subject: str | None = None) -> list[Memory]:
        """Current memories, oldest first."""
        mems = [m for m in self.memories.values() if subject is None or m.subject == subject]
        return sorted(mems, key=lambda m: m.created_at)

    async def apply(self, decision: Decision) -> Memory | None:
        """Apply one decision's action."""
        action = decision.action
        if action in ("reject", "review"):
            return None
        if action in ("store", "store_labeled", "redact"):
            mem = new_memory(decision)
            self.memories[mem.id] = mem
            return mem
        target = self._target(decision)
        if action == "update":
            mem = updated_memory(target, decision)
            self.memories[mem.id] = mem
            return mem
        if action == "merge":
            mem = merged_memory(target, decision)
            self.memories[mem.id] = mem
            return mem
        replacement = superseding_memory(target, decision)
        del self.memories[target.id]
        self.archive[target.id] = archived(target, decision, replacement)
        if replacement is not None:
            self.memories[replacement.id] = replacement
        return replacement

    def _target(self, decision: Decision) -> Memory:
        if decision.target is None or decision.target.id not in self.memories:
            raise StoreError(f"{decision.action} target not found in store")
        return self.memories[decision.target.id]
