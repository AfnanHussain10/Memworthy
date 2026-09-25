from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memgate.ledger import JsonlLedger, LedgerError, MemoryLedger
from memgate.models import Candidate, Decision, Memory, Patch
from memgate.stores.base import StoreError
from memgate.stores.dict import DictStore
from memgate.stores.rank import bm25_rank, tokens


def mem(text: str, id_: str, subject: str = "user") -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(id=id_, text=text, type="fact", subject=subject, created_at=now,
                  updated_at=now)


def decision(action: str, text: str = "I live in Riyadh", target: Memory | None = None,
             patch: Patch | None = None, **kw: object) -> Decision:
    return Decision(candidate=Candidate.from_text(text), action=action,  # type: ignore[arg-type]
                    type="fact", signals={}, rule="r", target=target, patch=patch,
                    policy="p", policy_version="1", judge="mock", latency_ms=1, **kw)


def test_tokens_and_bm25() -> None:
    assert tokens("I'm in Dubai, this WEEK!") == ["dubai", "week"]
    ranked = bm25_rank("where in Dubai", ["I live in Dubai", "I like tea", "Dubai Dubai"], 5)
    assert [i for i, _ in ranked] == [2, 0]
    assert bm25_rank("the a", ["x"], 3) == []
    assert bm25_rank("dubai", [], 3) == []


async def test_similar_filters_subject_and_uses_context() -> None:
    s = DictStore([mem("I live in Dubai", "a"), mem("Bob lives in Dubai", "b", "bob"),
                   mem("I like tea", "c")])
    c = Candidate.from_text("Actually only considering it", context="user: moved to Dubai")
    assert [m.id for m in await s.similar(c, 5)] == ["a"]
    assert [m.id for m in await s.all("bob")] == ["b"]
    assert len(await s.all()) == 3


async def test_actions() -> None:
    s = DictStore([mem("I live in Dubai", "a")])
    assert await s.apply(decision("reject")) is None
    assert await s.apply(decision("review")) is None
    m = await s.apply(decision("store_labeled", labels=["unverified"]))
    assert m is not None and m.labels == ["unverified"] and m.metadata["policy"] == "p"
    r = await s.apply(decision("redact", text="key sk-x", redacted_text="key [REDACTED:x]"))
    assert r is not None and r.text == "key [REDACTED:x]"
    target = s.memories["a"]
    u = await s.apply(decision("update", target=target,
                               patch=Patch(target_id="a", old_text=target.text,
                                           new_text="I live in Riyadh")))
    assert u is not None and u.id == "a" and u.text == "I live in Riyadh"
    assert u.metadata["previous_text"] == "I live in Dubai" and len(u.sources) == 1
    mg = await s.apply(decision("merge", text="Riyadh again", target=s.memories["a"]))
    assert mg is not None and len(mg.sources) == 2 and mg.text == "I live in Riyadh"
    sp = await s.apply(decision("supersede", text="I live in Jeddah", target=s.memories["a"],
                                patch=Patch(target_id="a", old_text="I live in Riyadh",
                                            new_text="I live in Jeddah")))
    assert sp is not None and sp.text == "I live in Jeddah" and sp.metadata["replaces"] == "a"
    assert "a" not in s.memories and s.archive["a"].metadata["superseded_by"] == sp.id
    with pytest.raises(StoreError):
        await s.apply(decision("update", target=mem("ghost", "zz")))
    with pytest.raises(StoreError):
        await s.apply(decision("merge"))


def test_jsonl_ledger_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "l.jsonl"
    led = JsonlLedger(path)
    assert list(led.read()) == []
    d1, d2 = decision("store"), decision("reject")
    led.record(d1)
    led.record(d2)
    lines = path.read_text().splitlines()
    assert json.loads(lines[0]) == {"memgate_ledger": 1} and len(lines) == 3
    assert [d.id for d in led.read()] == [d1.id, d2.id]
    assert next(iter(led.read())) == d1


def test_jsonl_ledger_errors_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"x": 1}\n')
    with pytest.raises(LedgerError, match="header"):
        list(JsonlLedger(bad).read())
    bad.write_text('{"memgate_ledger": 1}\nnot json\n')
    with pytest.raises(LedgerError, match="invalid JSON"):
        list(JsonlLedger(bad).read())
    monkeypatch.setenv("MEMGATE_LEDGER", str(tmp_path / "env.jsonl"))
    assert JsonlLedger().path == tmp_path / "env.jsonl"


def test_memory_ledger_jsonl() -> None:
    led = MemoryLedger()
    led.record(decision("store"))
    out = led.to_jsonl().splitlines()
    assert out[0] == '{"memgate_ledger": 1}' and len(out) == 2
    assert len(list(led.read())) == 1
