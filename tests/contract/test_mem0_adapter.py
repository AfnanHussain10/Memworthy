"""Mem0 adapter against the pinned mem0ai version with an in-memory Qdrant and a local
hashing embedder. No network: nothing calls an LLM because every write uses infer=False."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mem0")
os.environ.setdefault("MEM0_TELEMETRY", "false")

import mem0
from mem0 import Memory as Mem0Memory
from mem0.embeddings.base import EmbeddingBase
from qdrant_client import QdrantClient

from memworthy import Candidate, MemoryLedger, MockJudge
from memworthy.models import Decision, Patch, SignalValue
from memworthy.stores.base import StoreError
from memworthy.stores.mem0 import GatedMemory, Mem0Store

pytestmark = pytest.mark.contract
DIMS = 64


class HashEmbedder(EmbeddingBase):  # type: ignore[misc]
    def __init__(self) -> None:
        pass

    def embed(self, text: str, memory_action: Any = None) -> list[float]:
        v = [0.0] * DIMS
        for word in text.lower().split():
            v[int(hashlib.md5(word.strip(".,!?").encode()).hexdigest(), 16) % DIMS] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


@pytest.fixture
def client(tmp_path: Path) -> Any:
    cfg = {
        "vector_store": {"provider": "qdrant", "config": {
            "collection_name": "memworthy_test", "client": QdrantClient(":memory:"),
            "embedding_model_dims": DIMS}},
        "embedder": {"provider": "openai", "config": {"api_key": "unused",
                                                      "embedding_dims": DIMS}},
        "llm": {"provider": "openai", "config": {"api_key": "unused"}},
        "history_db_path": str(tmp_path / "history.db"),
    }
    m = Mem0Memory.from_config(cfg)
    m.embedding_model = HashEmbedder()

    def no_llm(*a: Any, **k: Any) -> Any:
        raise AssertionError("the LLM must never be called in these tests")

    m.llm.generate_response = no_llm
    return m


def test_pinned_version() -> None:
    major, minor = (int(x) for x in mem0.__version__.split(".")[:2])
    assert (major, minor) == (2, 2), "adapter verified against mem0ai 2.2.x"


def _d(action: str, text: str, target: Any = None, patch: Any = None) -> Decision:
    return Decision(candidate=Candidate.from_text(text), action=action,  # type: ignore[arg-type]
                    type="fact", signals={"type": SignalValue(name="type", kind="choice",
                                                              value="fact")},
                    rule="r", target=target, patch=patch, policy="personal-memory",
                    policy_version="1.1", judge="mock", latency_ms=1,
                    labels=["unverified"] if action == "store_labeled" else [])


async def test_store_actions(client: Any) -> None:
    store = Mem0Store(client, user_id="alice")
    m = await store.apply(_d("store", "I live in Dubai"))
    assert m is not None and m.text == "I live in Dubai" and m.type == "fact"
    labeled = await store.apply(_d("store_labeled", "I play chess"))
    assert labeled is not None and labeled.labels == ["unverified"]
    assert await store.apply(_d("reject", "nope")) is None
    found = await store.similar(Candidate.from_text("I moved to Riyadh",
                                                    context="user: I live in Dubai"), 5)
    assert found and found[0].id == m.id
    u = await store.apply(_d("update", "I live in Riyadh", target=m,
                             patch=Patch(target_id=m.id, old_text=m.text,
                                         new_text="I live in Riyadh")))
    assert u is not None and u.id == m.id and u.text == "I live in Riyadh"
    assert u.metadata["memworthy_previous_text"] == "I live in Dubai"
    back = await store.apply(_d("supersede", "Actually only considering it", target=u,
                                patch=Patch(target_id=u.id, old_text=u.text,
                                            new_text="I live in Dubai", restore=True)))
    assert back is not None and back.text == "I live in Dubai"
    merged = await store.apply(_d("merge", "Dubai again", target=back))
    assert merged is not None and len(merged.metadata["memworthy_merged"]) == 1
    gone = await store.apply(_d("supersede", "never mind", target=labeled))
    assert gone is None
    texts = sorted(x.text for x in await store.all())
    assert texts == ["I live in Dubai"]
    assert await store.all("someone-else") == []
    with pytest.raises(StoreError):
        await store.apply(_d("update", "x"))
    with pytest.raises(StoreError):
        Mem0Store(client)


def _judge() -> MockJudge:
    return MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                               "about_subject": 0.9, "sensitivity": 0.2, "retraction": 0.05},
                     rules=[("visiting|this week", {"type": "temporary"})])


def test_gated_memory_input_mode(client: Any) -> None:
    sent: list[Any] = []
    real_add = client.add

    def spy_add(messages: Any, **kw: Any) -> Any:
        sent.append((messages, kw))
        return real_add(messages, **kw)

    client.add = spy_add
    gm = GatedMemory(client, "personal-memory", judge=_judge(), ledger=MemoryLedger())
    key = "sk-proj-Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"
    out = gm.add([
        {"role": "system", "content": "be nice"},
        {"role": "user", "content": "I live in Lisbon"},
        {"role": "user", "content": "I'm visiting Rome this week"},
        {"role": "assistant", "content": "Enjoy Rome!"},
        {"role": "user", "content": f"my key is {key}"},
    ], user_id="bob", infer=False)
    [(messages, kwargs)] = sent
    assert kwargs == {"user_id": "bob", "infer": False}
    contents = [m["content"] for m in messages]
    assert "I live in Lisbon" in contents and "be nice" in contents
    assert not any("Rome" in c for c in contents)  # temporary + assistant rejected
    assert "my key is [REDACTED:openai]" in contents and not any(key in c for c in contents)
    assert [d["action"] for d in out["memworthy_decisions"]] == [
        "store", "reject", "reject", "redact"]
    stored = sorted(m["memory"] for m in gm.get_all(filters={"user_id": "bob"})["results"])
    assert stored == ["I live in Lisbon", "my key is [REDACTED:openai]"]  # Mem0 skips system


def test_gated_memory_nothing_left(client: Any) -> None:
    gm = GatedMemory(client, "personal-memory", judge=_judge(), ledger=MemoryLedger())
    out = gm.add("I'm visiting Paris this week", user_id="carol", infer=False)
    assert out["results"] == [] and out["memworthy_decisions"][0]["action"] == "reject"
    assert client.get_all(filters={"user_id": "carol"})["results"] == []


def test_gated_memory_candidate_mode_and_passthrough(client: Any) -> None:
    gm = GatedMemory(client, "personal-memory", mode="candidate", judge=_judge(),
                     ledger=MemoryLedger())
    out = gm.add([{"role": "user", "content": "I work as a nurse"},
                  {"role": "user", "content": "I'm visiting Oslo this week"}], user_id="dan")
    assert [r["event"] for r in out["results"]] == ["STORE"]
    stored = gm.get_all(filters={"user_id": "dan"})["results"]
    assert [m["memory"] for m in stored] == ["I work as a nurse"]
    assert stored[0]["metadata"]["memworthy_type"] == "fact"
    hits = gm.search("nurse", filters={"user_id": "dan"}, top_k=3)["results"]
    assert hits[0]["memory"] == "I work as a nurse"
    gm.delete(stored[0]["id"])
    assert gm.get_all(filters={"user_id": "dan"})["results"] == []
    with pytest.raises(ValueError):
        GatedMemory(client, "personal-memory", mode="bogus")
