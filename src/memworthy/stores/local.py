"""Shared action logic for stores that keep memories locally (dict, Markdown)."""

from __future__ import annotations

from memworthy.models import Candidate, Decision, Memory
from memworthy.stores.base import (
    StoreError,
    archived,
    merged_memory,
    new_memory,
    superseding_memory,
    updated_memory,
)
from memworthy.stores.rank import shortlist


class LocalStore:
    """Applies actions to an in-memory index; subclasses persist through two hooks."""

    def __init__(self, memories: list[Memory] | None = None) -> None:
        """Start with optional existing memories."""
        self.memories: dict[str, Memory] = {m.id: m for m in memories or []}
        self.archive: dict[str, Memory] = {}

    def _save(self, memory: Memory) -> None:
        """Persist a new or changed current memory (no-op in memory)."""

    def _retire(self, memory: Memory) -> None:
        """Persist a memory moving to the archive (no-op in memory)."""

    async def similar(self, candidate: Candidate, k: int) -> list[Memory]:
        """BM25 over memories of the same subject, padded with the most recent ones."""
        pool = [m for m in self.memories.values() if m.subject == candidate.subject]
        return shortlist(candidate, pool, k)

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
            return self._put(new_memory(decision))
        target = self._target(decision)
        if action == "update":
            return self._put(updated_memory(target, decision))
        if action == "merge":
            return self._put(merged_memory(target, decision))
        replacement = superseding_memory(target, decision)
        old = archived(target, decision, replacement)
        del self.memories[target.id]
        self.archive[target.id] = old
        self._retire(old)
        return self._put(replacement) if replacement is not None else None

    def _put(self, memory: Memory) -> Memory:
        self.memories[memory.id] = memory
        self._save(memory)
        return memory

    def _target(self, decision: Decision) -> Memory:
        if decision.target is None or decision.target.id not in self.memories:
            raise StoreError(f"{decision.action} target not found in store")
        return self.memories[decision.target.id]
