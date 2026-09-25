from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memgate import MockJudge
from memgate.cli import app
from memgate.evaluation import (
    calibration,
    ece,
    fit_temperature,
    fixture_stats,
    metrics,
    nll,
    reliability,
    run_pairs,
    scale,
    write_plots,
)
from memgate.pairs import expand_pairs
from memgate.policy.loader import load_policy
from memgate.reporting import summary_markdown

PAIRS = [{
    "template": "I {verb} {city}", "category": "temporary_vs_durable",
    "calibrate": {"signal": "durable", "positive": ["store"]},
    "fills": {"city": ["Lima", "Oslo"]},
    "cases": [{"verb": "live in", "expect": "store"}, {"verb": "am visiting", "expect": "reject"}],
}, {"template": "{t}", "category": "noise", "fills": {"t": ["hi"]},
    "cases": [{"expect": "reject"}]}]


def judge() -> MockJudge:
    return MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                               "about_subject": 0.9, "sensitivity": 0.1, "retraction": 0.0},
                     rules=[("visiting", {"type": "temporary", "durable": 0.2}),
                            ("Oslo", {"durable": 0.55}),
                            ("New message: hi\n", {"type": "noise"})])


async def test_metrics_end_to_end(tmp_path: Path) -> None:
    pol = load_policy("personal-memory")
    cases = await run_pairs(pol, judge(), expand_pairs(PAIRS))
    assert [c.correct for c in cases] == [True, True, False, True, True]  # Oslo: durable 0.55
    r = metrics(pol, cases, "mock", "m")
    assert r["accuracy"] == pytest.approx(0.8) and r["pairs"] == 2
    assert r["pair_consistency"] == 0.5
    assert r["categories"]["noise"]["pair_consistency"] is None
    assert r["confusion"]["store -> reject"] == 1 and r["failures"][0]["input"] == "I live in Oslo"
    cal = r["calibration"]["durable"]
    assert cal["n"] == 4 and cal["positives"] == 2
    md = summary_markdown(r)
    assert "Action accuracy | 80.0%" in md and "I live in Oslo" in md and "calibrated" in md
    assert {p.name for p in write_plots(r, tmp_path)} == {"accuracy_by_category.png",
                                                          "calibration_durable.png"}


def test_calibration_math() -> None:
    pts = [(0.9, 1), (0.8, 1), (0.3, 0), (0.2, 0)]
    assert ece([]) != ece([])  # nan
    assert ece(pts) == pytest.approx(0.2, abs=1e-9)
    assert [b["n"] for b in reliability(pts)] == [1, 1, 1, 1]
    t = fit_temperature(pts)
    assert t < 1 and nll(pts, t) < nll(pts, 1.0)
    assert scale(0.5, 0.3) == pytest.approx(0.5) and scale(0.9, 1.0) == pytest.approx(0.9)
    assert calibration([]) == {}


def test_fixture_stats(tmp_path: Path) -> None:
    assert fixture_stats(None) == {} and fixture_stats(tmp_path / "missing.json") == {}
    f = tmp_path / "fx.json"
    f.write_text(json.dumps({"memgate_fixtures": 1, "synthetic": False, "entries": {
        "a": {"latency_ms": 100, "raw": {"usage": {"input_tokens": 1000}}},
        "b": {"latency_ms": 300, "raw": {"usage": {"input_tokens": 3000}}}}}))
    s = fixture_stats(f)
    assert s["latency_ms_median"] == 200 and s["input_tokens_median"] == 2000
    assert s["cost_usd_per_candidate_median"] == pytest.approx(2000 * 0.042 / 1e6)


def test_eval_cli_writes_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = CliRunner().invoke(app, ["eval", "personal-memory", "--out", str(tmp_path / "res")])
    assert r.exit_code == 0, r.output
    data = json.loads((tmp_path / "res" / "personal-memory" / "metrics.json").read_text())
    assert data["model"] == "jev-1.13.0" and data["judge_errors"] == 0
    assert data["cases"] >= 250 and not data["calls"]["synthetic"]
    assert (tmp_path / "res" / "personal-memory" / "summary.md").exists()
    bad = CliRunner().invoke(app, ["eval", str(tmp_path / "nope.yaml")])
    assert bad.exit_code == 1
