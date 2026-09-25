"""Acceptance for milestone 4: replay, lint and review on fixture ledgers and policies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from memgate import Candidate, DictStore, Gate, MemoryLedger, MockJudge, RecordedJudge
from memgate.cli import app
from memgate.judges.recorded import bundled_fixture_path
from memgate.ledger import JsonlLedger
from memgate.policy.loader import load_policy, load_policy_text
from memgate.replay import replay, replay_rules
from memgate.testing import run_tests

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "tests" / "fixtures" / "ledgers" / "personal-memory.ledger.jsonl"
CHANGED = ROOT / "tests" / "fixtures" / "policies" / "personal-memory-durable-0.8.yaml"
OVERLAP = ROOT / "tests" / "fixtures" / "policies" / "overlapping-types.yaml"
runner = CliRunner()


def recorded() -> RecordedJudge:
    path = bundled_fixture_path("personal-memory")
    assert path is not None
    return RecordedJudge(path)


async def test_replay_flags_exactly_the_decisions_the_threshold_flips() -> None:
    old = list(JsonlLedger(LEDGER).read())
    new_policy = load_policy(CHANGED)
    # Oracle: re-run every test end to end under the new policy with the same recorded
    # answers (a threshold change leaves the questions, and so the fixture keys, unchanged).
    truth = await run_tests(new_policy, recorded())
    new_action = {r.decision.candidate.id: r.decision.action for r in truth}
    expected = {d.id for d in old if new_action[d.candidate.id] != d.action}
    results = await replay(new_policy, old)
    assert all(r.method == "rules" for r in results)
    assert {r.old.id for r in results if r.changed} == expected
    assert len(expected) == 8
    assert all(r.new is not None and r.new.rule == "low_durability"
               for r in results if r.changed)


def test_cli_replay_lists_changes() -> None:
    r = runner.invoke(app, ["replay", str(LEDGER), str(CHANGED), "--only-changed", "--json"])
    assert r.exit_code == 0, r.output
    rows = json.loads(r.stdout)
    assert len(rows) == 8 and all(x["changed"] and x["new_action"] == "reject" for x in rows)
    r = runner.invoke(app, ["replay", str(LEDGER), "personal-memory"])
    assert r.exit_code == 0 and "0 changed, 124 unchanged, 0 need live calls" in r.stdout


def test_replay_prompt_change_needs_live_then_rejudges(tmp_path: Path) -> None:
    text = CHANGED.read_text().replace(
        "Is this a lasting fact, preference or relationship", "Is this a durable fact")
    policy = load_policy_text(text)
    old = list(JsonlLedger(LEDGER).read())
    res = [replay_rules(policy, d) for d in old]
    live = [r for r in res if r.method == "needs_live"]
    short = [r for r in res if r.method == "rules"]
    assert live and all(r.reason == "policy questions changed" for r in live)
    assert short and all(r.old.type == "unknown" for r in short)  # short-circuited ones
    judge = MockJudge(defaults={"type": "fact", "durable": 0.95, "explicit": 0.9,
                                "about_subject": 0.9, "sensitivity": 0.1, "retraction": 0.0,
                                "conflict": "none"})
    import asyncio

    rejudged = asyncio.run(replay(policy, old, judge))
    assert {r.method for r in rejudged} == {"rules", "rejudged"}
    missing = asyncio.run(replay(policy, old[:5], recorded()))
    assert any(r.method == "needs_live" and "no recorded answer" in r.reason for r in missing)


def test_lint_cli() -> None:
    r = runner.invoke(app, ["lint", str(OVERLAP), "--strict"])
    assert r.exit_code == 1
    assert "overlapping-types" in r.stdout and "'trip' and 'travel'" in r.stdout
    for code in ("unused-signal", "unreachable-rule", "impossible-threshold", "vague-prompt",
                 "unused-conflict"):
        assert code in r.stdout
    assert runner.invoke(app, ["lint", str(OVERLAP)]).exit_code == 0
    for name in ("personal-memory", "dev-sessions"):
        r = runner.invoke(app, ["lint", name, "--strict"])
        assert r.exit_code == 0 and "0 warning(s)" in r.stdout


def test_review_accept_override_skip_and_export(tmp_path: Path) -> None:
    ledger_path = tmp_path / "l.jsonl"
    judge = MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                                "about_subject": 0.9, "retraction": 0.0,
                                "sensitivity": "Highly sensitive (health, finances, religion, "
                                               "precise location)"})
    gate = Gate("personal-memory", DictStore(), judge=judge, ledger=JsonlLedger(ledger_path))
    gate.evaluate([Candidate.from_text("I have asthma", subject="a"),
                   Candidate.from_text("I earn 90k", subject="b"),
                   Candidate.from_text("I pray daily", subject="c")])
    out = tmp_path / "tests.yaml"
    r = runner.invoke(app, ["review", str(ledger_path), "--export-tests", str(out)],
                      input="a\no\nstore\ns\n")
    assert r.exit_code == 0, r.output
    assert "3 decision(s) to review" in r.stdout and "exported 1 test(s)" in r.stdout
    assert yaml.safe_load(out.read_text()) == [{"input": "I earn 90k", "subject": "b",
                                                "expect": "store"}]
    r = runner.invoke(app, ["review", str(ledger_path)], input="o\nexplode\n")
    assert "1 decision(s) to review" in r.stdout and "unknown action" in r.stdout
    reviews = (tmp_path / "l.jsonl.reviews.jsonl").read_text().splitlines()
    assert [json.loads(x)["resolution"] for x in reviews] == ["accepted", "overridden"]


def test_cli_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("nope\n")
    assert runner.invoke(app, ["replay", str(bad), "personal-memory"]).exit_code == 1
    assert runner.invoke(app, ["review", str(bad)]).exit_code == 1


def test_errored_decisions_need_live() -> None:
    led = MemoryLedger()
    Gate("personal-memory", DictStore(), judge=MockJudge(fail=True), ledger=led).evaluate(
        [Candidate.from_text("I live in Oslo")])
    [res] = [replay_rules(load_policy("personal-memory"), d) for d in led.decisions]
    assert res.method == "needs_live" and res.new is None and not res.changed


@pytest.mark.parametrize("policy", ["personal-memory", "dev-sessions"])
def test_decisions_carry_questions_hash(policy: str) -> None:
    led = MemoryLedger()
    Gate(policy, DictStore(), judge=MockJudge(), ledger=led).evaluate(
        [Candidate.from_text("hello there")])
    assert led.decisions[0].questions_hash and len(led.decisions[0].questions_hash) == 16
