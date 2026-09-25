"""Mem0 adapter (``memgate[mem0]``): a MemoryStore over a Mem0 client, and GatedMemory.

Verified against mem0ai 2.2.0: add-without-inference is ``add(..., infer=False)``, search takes
``filters`` and ``top_k``, and ``update(memory_id, text=..., metadata=...)`` merges metadata.
Works with ``mem0.Memory`` and ``mem0.AsyncMemory``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime
from typing import Any

from memgate.gate import Gate, run_sync
from memgate.models import Candidate, Decision, Memory, SourceRef, utcnow
from memgate.sources.chat import split_messages
from memgate.stores.base import StoreError, memory_text

log = logging.getLogger("memgate.stores.mem0")
SCOPE_KEYS = ("user_id", "agent_id", "run_id")
PREFIX = "memgate_"


async def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or async Mem0 method without blocking the event loop."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


def _time(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return utcnow()


def to_memory(item: dict[str, Any], subject: str = "user") -> Memory:
    """Convert a Mem0 result item into a MemGate Memory."""
    meta = dict(item.get("metadata") or {})
    return Memory(
        id=str(item["id"]), text=str(item.get("memory", "")),
        type=str(meta.pop(f"{PREFIX}type", "memory")),
        subject=str(meta.pop(f"{PREFIX}subject", subject)),
        created_at=_time(item.get("created_at")), updated_at=_time(item.get("updated_at")),
        labels=[str(x) for x in meta.pop(f"{PREFIX}labels", []) or []],
        metadata=meta)


def _results(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("results", [])
    return [v for v in value or [] if isinstance(v, dict)]


class Mem0Store:
    """MemoryStore backed by a Mem0 client, bound to one user/agent/run scope."""

    def __init__(self, client: Any, user_id: str | None = None, agent_id: str | None = None,
                 run_id: str | None = None) -> None:
        """Wrap ``client``; at least one scope id is required by Mem0."""
        self.client = client
        self.scope = {k: v for k, v in (("user_id", user_id), ("agent_id", agent_id),
                                        ("run_id", run_id)) if v}
        if not self.scope:
            raise StoreError("Mem0Store needs user_id, agent_id or run_id")

    @classmethod
    def from_env(cls) -> Mem0Store:
        """Default Mem0 client (its own config and keys) scoped by MEMGATE_MEM0_USER_ID."""
        import os

        from mem0 import Memory as Mem0Memory

        return cls(Mem0Memory(), user_id=os.environ.get("MEMGATE_MEM0_USER_ID", "default"))

    async def similar(self, candidate: Candidate, k: int) -> list[Memory]:
        """Mem0 search with the candidate text plus its context, in this store's scope."""
        query = f"{candidate.text}\n{candidate.context}".strip()
        found = await _call(self.client.search, query, filters=dict(self.scope), top_k=k)
        return [to_memory(item, candidate.subject) for item in _results(found)][:k]

    async def all(self, subject: str | None = None) -> list[Memory]:
        """All memories in scope (optionally one MemGate subject)."""
        found = await _call(self.client.get_all, filters=dict(self.scope), top_k=10_000)
        mems = [to_memory(item) for item in _results(found)]
        return [m for m in mems if subject is None or m.subject == subject]

    def _meta(self, decision: Decision, **extra: Any) -> dict[str, Any]:
        meta = {f"{PREFIX}type": decision.type, f"{PREFIX}subject": decision.candidate.subject,
                f"{PREFIX}labels": list(decision.labels),
                f"{PREFIX}decision_id": decision.id, f"{PREFIX}policy": decision.policy,
                f"{PREFIX}policy_version": decision.policy_version}
        meta.update({f"{PREFIX}{k}": v for k, v in extra.items()})
        return meta

    async def _get(self, memory_id: str) -> Memory:
        item = await _call(self.client.get, memory_id)
        if not item:
            raise StoreError(f"Mem0 memory {memory_id} not found")
        return to_memory(item)

    async def apply(self, decision: Decision) -> Memory | None:
        """Map MemGate actions onto Mem0 add/update/delete."""
        action = decision.action
        if action in ("reject", "review"):
            return None
        if action in ("store", "store_labeled", "redact"):
            role = decision.candidate.source.role
            msg = {"role": role if role in ("user", "assistant") else "user",
                   "content": memory_text(decision)}
            res = await _call(self.client.add, [msg], **self.scope, infer=False,
                              metadata=self._meta(decision))
            items = _results(res)
            if not items:
                raise StoreError("Mem0 add returned no memory")
            return await self._get(str(items[0]["id"]))
        if decision.target is None:
            raise StoreError(f"{action} needs a target memory")
        target_id = decision.target.id
        if action == "merge":
            merged = list(decision.target.metadata.get(f"{PREFIX}merged", []))
            merged.append(decision.id)
            await _call(self.client.update, target_id, metadata={f"{PREFIX}merged": merged})
            return await self._get(target_id)
        if action == "supersede" and decision.patch is None:
            await _call(self.client.delete, target_id)  # archive-only retraction
            return None
        new_text = decision.patch.new_text if decision.patch else memory_text(decision)
        await _call(self.client.update, target_id, text=new_text,
                    metadata=self._meta(decision, previous_text=decision.target.text))
        return await self._get(target_id)


class GatedMemory:
    """Wraps a Mem0 client so ``add`` is gated; every other method passes through.

    ``mode="input"`` gates raw messages before Mem0's own extraction sees them;
    ``mode="candidate"`` gates candidates (from ``extractor`` or one per user message) and
    writes approved ones with ``infer=False``.
    """

    def __init__(self, client: Any, policy: Any, mode: str = "input",
                 **gate_kwargs: Any) -> None:
        """Keep the client; ``gate_kwargs`` go to :class:`Gate` (judge, ledger, extractor)."""
        if mode not in ("input", "candidate"):
            raise ValueError("mode must be 'input' or 'candidate'")
        self.client = client
        self.policy = policy
        self.mode = mode
        self.gate_kwargs = gate_kwargs
        self.last_decisions: list[Decision] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def _gate(self, scope: dict[str, str], apply: bool) -> Gate:
        return Gate(self.policy, Mem0Store(self.client, **scope), apply=apply,
                    **self.gate_kwargs)

    def add(self, messages: Any, **kwargs: Any) -> Any:
        """Same signature as Mem0's ``add``; returns Mem0's result plus ``memgate_decisions``."""
        return run_sync(self.aadd(messages, **kwargs))

    async def aadd(self, messages: Any, **kwargs: Any) -> Any:
        """Async form of :meth:`add`."""
        msgs = [{"role": "user", "content": messages}] if isinstance(messages, str) \
            else [dict(m) for m in messages]
        scope = {k: kwargs[k] for k in SCOPE_KEYS if kwargs.get(k)}
        if self.mode == "candidate":
            return await self._add_candidates(msgs, scope)
        gate = self._gate(scope, apply=False)
        cands = _message_candidates(msgs)
        decisions = await gate.aevaluate([c for _, c in cands])
        self.last_decisions = decisions
        verdict = {i: d for (i, _), d in zip(cands, decisions, strict=True)}
        kept = []
        for i, m in enumerate(msgs):
            d = verdict.get(i)
            if d is None:
                kept.append(m)  # system messages are not memories; Mem0 skips them
            elif d.action in ("reject", "review"):
                continue
            elif d.redacted_text is not None:
                kept.append({**m, "content": d.redacted_text})
            else:
                kept.append(m)
        payload = [d.model_dump(mode="json") for d in decisions]
        if not any(m.get("role") != "system" for m in kept):
            return {"results": [], "memgate_decisions": payload}
        result = await _call(self.client.add, kept, **kwargs)
        if isinstance(result, dict):
            result = {**result, "memgate_decisions": payload}
        return result

    async def _add_candidates(self, msgs: list[dict[str, Any]], scope: dict[str, str]) -> Any:
        gate = self._gate(scope, apply=True)
        decisions = await gate.aingest_messages(msgs)
        self.last_decisions = decisions
        written = [d for d in decisions if d.action not in ("reject", "review")]
        return {"results": [{"memory": memory_text(d), "event": d.action.upper()}
                            for d in written],
                "memgate_decisions": [d.model_dump(mode="json") for d in decisions]}


def _message_candidates(msgs: list[dict[str, Any]]) -> list[tuple[int, Candidate]]:
    """One candidate per user or assistant message, with earlier messages as context."""
    out: list[tuple[int, Candidate]] = []
    users = {id(m) for m in msgs if m.get("role") == "user"}
    user_cands = iter(split_messages(msgs))
    for i, m in enumerate(msgs):
        role = m.get("role")
        text = str(m.get("content", "")).strip()
        if not text:
            continue
        if id(m) in users:
            out.append((i, next(user_cands)))
        elif role == "assistant":
            prev = "\n".join(f"{p.get('role')}: {p.get('content')}" for p in msgs[max(0, i - 3):i])
            out.append((i, Candidate(text=text, source=SourceRef(role="assistant", text=text),
                                     context=prev)))
    return out


__all__ = ["GatedMemory", "Mem0Store", "to_memory"]
