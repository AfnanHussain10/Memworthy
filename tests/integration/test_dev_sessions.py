"""Acceptance for milestone 3: gate the fixture sessions into a Markdown knowledge base."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memgate import Gate, MemoryLedger, RecordedJudge
from memgate.cli import app
from memgate.judges.recorded import bundled_fixture_path
from memgate.policy.loader import load_policy
from memgate.stores.markdown import MarkdownStore
from memgate.testing import run_tests

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = ROOT / "tests" / "fixtures" / "sessions"
SNAPSHOT = ROOT / "tests" / "fixtures" / "snapshots" / "dev-sessions-kb"
VOLATILE = re.compile(r"^(id|created_at|updated_at|  decision_id|  superseded_by_decision):.*\n",
                      re.MULTILINE)


def normalized(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*.md")):
        rel = re.sub(r"-[0-9a-f]{6}\.md$", ".md", str(path.relative_to(root)))
        out[rel] = VOLATILE.sub("", path.read_text(encoding="utf-8"))
    return out


def recorded() -> RecordedJudge:
    path = bundled_fixture_path("dev-sessions")
    assert path is not None
    judge = RecordedJudge(path)
    assert not judge.synthetic
    return judge


def test_cli_run_matches_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    kb = tmp_path / "kb"
    result = CliRunner().invoke(app, [
        "run", "dev-sessions", str(SESSIONS), "--store", f"markdown:{kb}", "--judge", "recorded",
        "--ledger", str(tmp_path / "ledger.jsonl")])
    assert result.exit_code == 0, result.output
    assert "noise_dropped: 1" in result.stdout and "errors" not in result.output
    got = normalized(kb)
    if os.environ.get("MEMGATE_UPDATE_SNAPSHOTS"):
        shutil.rmtree(SNAPSHOT, ignore_errors=True)
        for rel, text in got.items():
            (SNAPSHOT / rel).parent.mkdir(parents=True, exist_ok=True)
            (SNAPSHOT / rel).write_text(text, encoding="utf-8")
    assert got == normalized(SNAPSHOT)
    everything = "\n".join(got.values())
    # Noise episodes (starting a dev server, asking about repo access) produce no files.
    assert "dev server" not in everything and "can see the repository" not in everything
    # The fake key in the Goodreads episode is redacted everywhere, ledger included.
    assert "sk-proj-Ex4mple" not in everything
    assert "sk-proj-Ex4mple" not in (tmp_path / "ledger.jsonl").read_text()
    assert "[REDACTED:openai]" in everything


def test_gate_ingest_sessions_api(tmp_path: Path) -> None:
    store = MarkdownStore(tmp_path / "kb")
    gate = Gate("dev-sessions", store, judge=recorded(), ledger=MemoryLedger())
    decisions = gate.ingest_sessions(SESSIONS)
    assert len(decisions) == 11 and all(d.error is None for d in decisions)
    assert {d.candidate.subject for d in decisions} == {"bookshelf"}
    labels = {tuple(d.labels) for d in decisions}
    assert ("unverified",) in labels and ("redacted",) in labels


async def test_builtin_tests_pass_with_recorded_answers() -> None:
    policy = load_policy("dev-sessions")
    assert len(policy.spec.tests) >= 100
    results = await run_tests(policy, recorded())
    assert [(r.test.input, r.reason) for r in results if not r.passed] == []
