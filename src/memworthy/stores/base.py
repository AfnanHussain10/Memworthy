"""MemoryStore interface and shared helpers for applying decisions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from memworthy.models import Candidate, Decision, Memory, SourceRef, new_id, utcnow


class StoreError(Exception):
    """A store could not apply a decision."""


@runtime_checkable
class MemoryStore(Protocol):
    """Where memories live. Memworthy never owns storage; stores adapt actions to a backend."""

    async def similar(self, candidate: Candidate, k: int) -> list[Memory]:
        """Return up to ``k`` existing memories that may conflict with the candidate."""
        ...

    async def apply(self, decision: Decision) -> Memory | None:
        """Apply the decision's action; return the created or changed memory."""
        ...

    async def all(self, subject: str | None = None) -> list[Memory]:
        """Return all current (non-archived) memories, optionally for one subject."""
        ...


WRITE_ACTIONS = frozenset({"store", "store_labeled", "redact", "update", "merge", "supersede"})


def memory_text(decision: Decision) -> str:
    """Text to store for a decision: the redacted text whenever redaction happened."""
    return decision.redacted_text or decision.candidate.text


def new_memory(decision: Decision, text: str | None = None, type_: str | None = None,
               extra_metadata: dict[str, object] | None = None) -> Memory:
    """Build a new Memory from a decision."""
    now = utcnow()
    labels = list(decision.labels)
    metadata: dict[str, object] = {
        "policy": decision.policy,
        "policy_version": decision.policy_version,
        "decision_id": decision.id,
    }
    type_sig = decision.signals.get("type")
    if type_sig is not None and type_sig.confidence is not None:
        metadata["confidence"] = type_sig.confidence
    for key in ("files", "commit", "dependency_versions", "referenced_files"):
        if key in decision.candidate.metadata:
            metadata[key] = decision.candidate.metadata[key]
    metadata.update(extra_metadata or {})
    return Memory(
        id=new_id(),
        text=text if text is not None else memory_text(decision),
        type=type_ or decision.type,
        subject=decision.candidate.subject,
        created_at=now,
        updated_at=now,
        sources=[_source(decision.candidate)],
        labels=labels,
        metadata=metadata,
    )


def _source(c: Candidate) -> SourceRef:
    return c.source


def updated_memory(target: Memory, decision: Decision) -> Memory:
    """The target after an ``update``: new text, previous text kept in metadata."""
    new_text = decision.patch.new_text if decision.patch else memory_text(decision)
    meta = dict(target.metadata)
    meta["previous_text"] = target.text
    meta["decision_id"] = decision.id
    meta["policy_version"] = decision.policy_version
    return target.model_copy(update={
        "text": new_text,
        "updated_at": utcnow(),
        "sources": [*target.sources, decision.candidate.source],
        "labels": sorted(set(target.labels) | set(decision.labels)),
        "metadata": meta,
    })


def merged_memory(target: Memory, decision: Decision) -> Memory:
    """The target after a ``merge``: the candidate's source appended."""
    return target.model_copy(update={
        "updated_at": utcnow(),
        "sources": [*target.sources, decision.candidate.source],
    })


def superseding_memory(target: Memory, decision: Decision) -> Memory | None:
    """The memory created by a ``supersede``, or None for archive-only."""
    if decision.patch is None:
        return None
    if decision.patch.restore:
        return new_memory(decision, text=decision.patch.new_text, type_=target.type,
                          extra_metadata={"restored_from": target.id})
    return new_memory(decision, text=decision.patch.new_text,
                      extra_metadata={"replaces": target.id})


def archived(target: Memory, decision: Decision, replacement: Memory | None) -> Memory:
    """The target as stored in the archive after being superseded."""
    meta = dict(target.metadata)
    meta["superseded_by"] = replacement.id if replacement else None
    meta["superseded_by_decision"] = decision.id
    return target.model_copy(update={"metadata": meta, "updated_at": utcnow()})
