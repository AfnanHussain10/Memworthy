from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memworthy import __version__
from memworthy.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)  # no .env in the working directory
    return tmp_path


def test_version() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == __version__


def test_test_recorded_passes() -> None:
    r = runner.invoke(app, ["test", "personal-memory", "--judge", "recorded"])
    assert r.exit_code == 0, r.stdout
    assert "passed (100.0%)" in r.stdout


def test_test_json_output() -> None:
    r = runner.invoke(app, ["test", "personal-memory", "--json"])
    data = json.loads(r.stdout)
    assert data["passed"] == data["total"] >= 100 and data["judge"] == "recorded"
    assert {"input", "action", "rule", "signals"} <= set(data["results"][0])


def test_test_mock_fails_and_prints_signals() -> None:
    r = runner.invoke(app, ["test", "personal-memory", "--judge", "mock"])
    assert r.exit_code == 1
    assert "FAIL [" in r.stdout and "type=" in r.stdout


def test_test_pairs_file(tmp_path: Path) -> None:
    pairs = tmp_path / "p.yaml"
    pairs.write_text('- template: "{t}"\n  fills: {t: [hello]}\n  cases:\n'
                     "    - {role: assistant, expect: reject}\n")
    r = runner.invoke(app, ["test", "personal-memory", "--judge", "mock", "--pairs", str(pairs)])
    assert r.exit_code == 0, r.stdout


def test_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = runner.invoke(app, ["test", "no-such-policy"])
    assert r.exit_code == 1 and "not found" in r.output
    pol = tmp_path / "p.yaml"
    pol.write_text("policy: p\nversion: '1'\ntypes: {a: A, b: B}\nrules:\n  - {else: store}\n")
    r = runner.invoke(app, ["test", str(pol)])
    assert r.exit_code == 1 and "no tests" in r.output
    pol.write_text(pol.read_text() + "tests:\n  - {input: x, expect: store}\n")
    r = runner.invoke(app, ["test", str(pol)])
    assert r.exit_code == 1 and "--fixtures" in r.output
    r = runner.invoke(app, ["test", str(pol), "--judge", "gpt"])
    assert r.exit_code == 1 and "--judge" in r.output
    r = runner.invoke(app, ["test", str(pol), "--pairs", str(tmp_path / "missing.yaml")])
    assert r.exit_code == 1
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    r = runner.invoke(app, ["test", str(pol), "--judge", "jev"])
    assert r.exit_code == 1 and "TYPESAFE_API_KEY" in r.output
    r = runner.invoke(app, ["record", str(pol), "tests", "--out", str(tmp_path / "f.json")])
    assert r.exit_code == 1 and "TYPESAFE_API_KEY" in r.output


def test_synthetic_fixture_warning(tmp_path: Path) -> None:
    pol = tmp_path / "p.yaml"
    pol.write_text("policy: p\nversion: '1'\ntypes: {a: A, b: B}\nrules:\n  - {else: store}\n"
                   "tests:\n  - {input: x, expect: store}\n")
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"memworthy_fixtures": 1, "synthetic": True, "entries": {}}))
    r = runner.invoke(app, ["test", str(pol), "--fixtures", str(fx)])
    assert r.exit_code == 1 and "synthetic" in r.output
