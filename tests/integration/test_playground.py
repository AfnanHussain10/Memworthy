"""Playground backend: replay mode works without a key; live mode is guarded and labeled."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from playground.backend import app as app_module
from playground.backend.limits import LiveLimits


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return TestClient(app_module.app)


def test_config_without_key(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    assert cfg["live_available"] is False
    assert set(cfg["templates"]) == {"personal-memory", "dev-sessions"}
    assert [m["content"] for m in cfg["demo"]][2] == "I moved to Riyadh last week"


def test_guided_demo_replays_from_recorded_answers(client: TestClient) -> None:
    demo = client.get("/api/config").json()["demo"]
    r = client.post("/api/run", json={"messages": demo}).json()
    decisions = [s["decision"] for s in r["steps"]]
    assert [d["action"] for d in decisions] == ["store", "reject", "update", "supersede"]
    assert all(d["mode"] == "recorded" for d in decisions)
    assert decisions[1]["reason"].startswith("temporary")
    assert decisions[3]["reason"].startswith("retraction")
    assert [m["text"] for m in r["steps"][-1]["memories"]] == ["I live in Dubai"]
    assert r["steps"][2]["memories"][0]["previous_text"] == "I live in Dubai"
    assert r["ledger"].startswith('{"memworthy_ledger": 1}')


def test_rule_edit_changes_decision(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    yaml = "\n".join(line for line in cfg["templates"]["personal-memory"]["yaml"].splitlines()
                     if "name: retracted" not in line)
    r = client.post("/api/run", json={"messages": cfg["demo"], "policy_yaml": yaml}).json()
    last = r["steps"][-1]
    assert last["decision"]["action"] == "reject"  # no rollback: an intent is rejected
    assert last["decision"]["mode"] == "recorded"  # questions unchanged, answers recorded
    assert [m["text"] for m in last["memories"]] == ["I moved to Riyadh last week"]


def test_new_input_needs_live_and_is_labeled(client: TestClient) -> None:
    r = client.post("/api/run", json={"messages": [{"role": "user", "content":
                                                    "I collect antique typewriters"}],
                                      "live": True}).json()
    d = r["steps"][0]["decision"]
    assert d["mode"] == "needs-live" and d["action"] == "review"


def test_input_limits_and_policy_errors(client: TestClient) -> None:
    long = [{"role": "user", "content": "x" * 301}]
    assert client.post("/api/run", json={"messages": long}).status_code == 400
    bad = client.post("/api/run", json={"messages": [], "policy_yaml": "policy: x\n: :"})
    assert bad.status_code == 400
    v = client.post("/api/validate", json={"policy_yaml": "policy: x\nversion: 1\ntypes: "
                                           "{a: A}\nrules:\n  - {when: 'nope', then: store}\n"
                                           "  - {else: store}\n"}).json()
    assert v["ok"] is False and v["line"] == 5
    assert client.post("/api/run", json={"template": "nope"}).status_code == 400


def test_session_demo(client: TestClient) -> None:
    r = client.post("/api/sessions", json={}).json()
    assert len(r["episodes"]) == 12 and sum(e["dropped"] for e in r["episodes"]) == 1
    assert all(d["mode"] == "recorded" for d in r["decisions"])
    assert len(r["files"]) == 9
    everything = "".join(f["markdown"] for f in r["files"])
    assert "sk-proj-Ex4mple" not in everything and "[REDACTED:openai]" in everything


def test_policy_tests_and_eval_and_events(client: TestClient) -> None:
    cfg = client.get("/api/config").json()
    t = client.post("/api/test", json={"template": "personal-memory",
                                       "policy_yaml": cfg["templates"]["personal-memory"]["yaml"]}
                    ).json()
    assert t["passed"] == t["total"] >= 100 and t["needs_live"] == 0
    ev = client.get("/api/eval").json()
    assert ev["personal-memory"]["model"] == "jev-1.13.0"
    assert ev["longmemeval"]["status"] == "pending"
    client.post("/api/event", json={"name": "visit"})
    client.post("/api/event", json={"name": "not-an-event"})
    counts = client.get("/api/stats").json()["counters"]
    assert counts.get("visit", 0) >= 1 and "not-an-event" not in counts


def test_live_limits() -> None:
    lim = LiveLimits(per_ip_per_hour=2, global_per_hour=3, daily_cap_usd=1.0)
    assert lim.check("a", now=0) is None
    lim.record("a", 100, now=0)
    lim.record("a", 100, now=1)
    assert "hour" in (lim.check("a", now=2) or "")
    assert lim.check("b", now=2) is None
    lim.record("b", 100, now=2)
    assert "busy" in (lim.check("c", now=3) or "")
    assert lim.check("a", now=4000) is None  # window slid
    lim.record("c", 30_000_000, now=4000)  # 30M tokens * $0.042/M = $1.26
    assert "budget" in (lim.check("d", now=4001) or "")


async def test_hybrid_judge_live_path() -> None:
    from memworthy.judges.base import Question
    from playground.backend.judge import HybridJudge

    class FakeJev:
        async def raw(self, state: str, questions: list[Question]) -> tuple[dict[str, Any], int]:
            return ({"model": "jev-1.13.0", "usage": {"input_tokens": 500},
                     "answers": {"d": {"type": "noul", "noul": 0.8}}}, 900)

    lim = LiveLimits()
    j = HybridJudge({}, {}, FakeJev(), lim, "ip")
    q = [Question(name="d", kind="noul", prompt="Durable?")]
    res = await j.judge("state", q)
    assert res.answers["d"].value == 0.8 and j.sources["state"] == "live"
    assert len(j.new_entries) == 1 and lim.spent_usd > 0
    again = HybridJudge({}, j.new_entries, None, lim, "ip")
    await again.judge("state", q)
    assert again.sources["state"] == "live"  # client-held live answer, still labeled live


def test_config_describes_rules_and_signals(client: TestClient) -> None:
    pm = client.get("/api/config").json()["templates"]["personal-memory"]
    rules = {r["id"]: r for r in pm["rules"]}
    assert rules["retracted"]["then"] == "supersede" and rules["retracted"]["restore"] is True
    line = pm["yaml"].splitlines()[rules["retracted"]["line"] - 1]
    assert line.strip().startswith("- {name: retracted")
    assert pm["signals"]["durable"].startswith("Is this a lasting fact")
    assert pm["signals"]["secret"] == "code check: secret_scan"
    assert "conflict" in pm["signals"] and "temporary" in pm["type_help"]


def test_session_policy_edit_applies(client: TestClient) -> None:
    yaml = client.get("/api/config").json()["templates"]["dev-sessions"]["yaml"]
    edited = yaml.replace("then: store_labeled, label: unverified}", "then: reject}", 1)
    r = client.post("/api/sessions", json={"policy_yaml": edited})
    assert r.status_code == 200  # the template is longer than the old 20k limit
    actions = [d["action"] for d in r.json()["decisions"]]
    assert "store_labeled" not in actions and actions.count("reject") == 2


def test_index_is_not_cached(client: TestClient) -> None:
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache" and '<div id="root">' in r.text
