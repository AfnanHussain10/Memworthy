"""Full Gate runs over the personal-memory template with recorded and mock judges."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memgate import Candidate, DictStore, Gate, MemoryLedger, MockJudge, RecordedJudge
from memgate.judges.recorded import bundled_fixture_path
from memgate.models import SourceRef
from memgate.policy.loader import load_policy
from memgate.testing import run_tests

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "src" / "memgate" / "templates" / "demos" / "personal-memory.chat.json"
SECRETS = ROOT / "tests" / "fixtures" / "secrets.jsonl"


def recorded() -> RecordedJudge:
    path = bundled_fixture_path("personal-memory")
    assert path is not None
    judge = RecordedJudge(path)
    assert not judge.synthetic, "bundled fixtures must be recorded from real Jev calls"
    return judge


async def test_builtin_tests_pass_with_recorded_answers() -> None:
    policy = load_policy("personal-memory")
    assert len(policy.spec.tests) >= 100
    results = await run_tests(policy, recorded())
    failures = [(r.test.input, r.reason) for r in results if not r.passed]
    assert failures == []


def test_demo_replays_store_reject_update_rollback() -> None:
    store = DictStore()
    gate = Gate("personal-memory", store, judge=recorded(), ledger=MemoryLedger())
    decisions = gate.ingest_messages(json.loads(DEMO.read_text()))
    assert [d.action for d in decisions] == ["store", "reject", "update", "supersede"]
    assert decisions[1].type == "temporary"
    assert decisions[2].patch is not None and decisions[2].patch.old_text == "I live in Dubai"
    assert decisions[3].patch is not None and decisions[3].patch.restore
    assert [m.text for m in store.memories.values()] == ["I live in Dubai"]
    assert [m.text for m in store.archive.values()] == ["I moved to Riyadh last week"]
    assert all(d.judge == "recorded" and d.model == "jev-1.13.0" for d in decisions[:4])


def _secret_candidates() -> list[tuple[Candidate, str]]:
    out = []
    for line in SECRETS.read_text().splitlines():
        item = json.loads(line)
        cand = Candidate(text=item["text"], context=item.get("context", ""),
                         source=SourceRef(role="user",
                                          text=item.get("source_text", item["text"])))
        out.append((cand, item["secret"]))
    return out


@pytest.mark.parametrize("policy", ["personal-memory"])
def test_secrets_never_reach_the_judge(policy: str) -> None:
    spy = MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                              "about_subject": 0.9})
    store, ledger = DictStore(), MemoryLedger()
    gate = Gate(policy, store, judge=spy, ledger=ledger)
    pairs = _secret_candidates()
    decisions = gate.evaluate([c for c, _ in pairs])
    sent = "\n".join(state + json.dumps([q.model_dump() for q in qs])
                     for state, qs in spy.calls)
    written = ledger.to_jsonl() + json.dumps([m.model_dump(mode="json")
                                              for m in store.memories.values()])
    for (cand, secret), d in zip(pairs, decisions, strict=True):
        assert secret in cand.text + cand.context + cand.source.text  # fixture sanity
        assert secret not in sent, f"secret sent to judge: {cand.text[:30]}"
        assert secret not in written, f"secret written: {cand.text[:30]}"
        assert d.action == "redact" and d.redacted_text is not None
        assert "[REDACTED:" in d.redacted_text + d.candidate.context + d.candidate.source.text
    assert len(spy.calls) == len(pairs)


def test_mock_judge_full_run() -> None:
    judge = MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                                "about_subject": 0.9, "sensitivity": 0.2,
                                "retraction": 0.05},
                      rules=[("visiting", {"type": "temporary"})])
    store = DictStore()
    gate = Gate("personal-memory", store, judge=judge, ledger=MemoryLedger())
    ds = gate.ingest_messages([
        {"role": "user", "content": "I live in Lisbon"},
        {"role": "user", "content": "I am visiting Rome"},
        {"role": "assistant", "content": "Great!"},
    ])
    assert [d.action for d in ds] == ["store", "reject"]
    assert [m.text for m in store.memories.values()] == ["I live in Lisbon"]
