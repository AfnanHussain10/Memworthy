"""Evaluation on contrast pairs: accuracy, pair consistency, calibration, latency and cost.

Labels come from the pair templates, never from a judge. Calibration is measured for the
signal a category names (``calibrate: {signal, positive}``): the signal's probability should
track whether the expected action is one of ``positive``. Temperature scaling is fitted and
scored with two-fold cross-validation over pair groups, so the "after" number is not fitted
on the data it is scored on.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memgate.judges.base import Judge
from memgate.models import Decision
from memgate.pairs import PairCase
from memgate.policy.loader import Policy
from memgate.testing import run_tests

JEV_PRICE_PER_MILLION_INPUT = 0.042  # USD, docs.typesafe.ai/models (output tokens are free)
BINS = 10


@dataclass
class EvalCase:
    """One contrast case with the decision the policy made."""

    pair: PairCase
    decision: Decision
    correct: bool


async def run_pairs(policy: Policy, judge: Judge, cases: list[PairCase]) -> list[EvalCase]:
    """Decide every case (fresh store per case) and mark correctness."""
    results = await run_tests(policy, judge, [c.test for c in cases])
    return [EvalCase(c, r.decision, r.passed) for c, r in zip(cases, results, strict=True)]


def _clip(p: float) -> float:
    return min(max(p, 1e-4), 1 - 1e-4)


def scale(p: float, t: float) -> float:
    """Temperature-scale a probability: sigmoid(logit(p) / t)."""
    z = math.log(_clip(p) / (1 - _clip(p))) / t
    return 1 / (1 + math.exp(-z))


def nll(points: list[tuple[float, int]], t: float) -> float:
    """Mean negative log-likelihood of labels under temperature ``t``."""
    total = 0.0
    for p, y in points:
        q = _clip(scale(p, t))
        total -= math.log(q) if y else math.log(1 - q)
    return total / max(len(points), 1)


def fit_temperature(points: list[tuple[float, int]]) -> float:
    """Temperature minimizing NLL (golden-section search over log t in [-3, 3])."""
    lo, hi = -3.0, 3.0
    g = (math.sqrt(5) - 1) / 2
    for _ in range(60):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if nll(points, math.exp(a)) < nll(points, math.exp(b)):
            hi = b
        else:
            lo = a
    return math.exp((lo + hi) / 2)


def reliability(points: list[tuple[float, int]]) -> list[dict[str, float]]:
    """Equal-width bins: mean predicted probability vs observed positive rate."""
    bins: list[list[tuple[float, int]]] = [[] for _ in range(BINS)]
    for p, y in points:
        bins[min(int(p * BINS), BINS - 1)].append((p, y))
    return [{"lo": i / BINS, "hi": (i + 1) / BINS, "n": len(b),
             "confidence": statistics.mean(p for p, _ in b),
             "accuracy": statistics.mean(y for _, y in b)}
            for i, b in enumerate(bins) if b]


def ece(points: list[tuple[float, int]]) -> float:
    """Expected calibration error over equal-width bins."""
    n = len(points)
    return sum(b["n"] / n * abs(b["accuracy"] - b["confidence"])
               for b in reliability(points)) if n else float("nan")


def calibration(cases: list[EvalCase]) -> dict[str, Any]:
    """Per-signal calibration before and after cross-validated temperature scaling."""
    by_signal: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    for c in cases:
        cal = c.pair.calibrate
        if not cal:
            continue
        sig = c.decision.signals.get(str(cal["signal"]))
        if sig is None or not isinstance(sig.value, float):
            continue
        label = int(any(a in cal.get("positive", []) for a in c.pair.test.expected))
        by_signal[str(cal["signal"])].append((c.pair.pair_id, float(sig.value), label))
    out: dict[str, Any] = {}
    for name, rows in sorted(by_signal.items()):
        points = [(p, y) for _, p, y in rows]
        groups = sorted({g for g, _, _ in rows})
        folds = [set(groups[0::2]), set(groups[1::2])]
        after: list[tuple[float, int]] = []
        for k in (0, 1):
            train = [(p, y) for g, p, y in rows if g not in folds[k]]
            test = [(p, y) for g, p, y in rows if g in folds[k]]
            t = fit_temperature(train) if train else 1.0
            after += [(scale(p, t), y) for p, y in test]
        out[name] = {
            "n": len(points), "positives": sum(y for _, y in points),
            "ece_before": ece(points), "ece_after_cv": ece(after),
            "temperature_all": fit_temperature(points),
            "reliability_before": reliability(points), "reliability_after_cv": reliability(after),
        }
    return out


def fixture_stats(fixture_path: Path | None) -> dict[str, Any]:
    """Latency and token cost of the live calls recorded in a fixture file."""
    if fixture_path is None or not fixture_path.exists():
        return {}
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    entries = list((data.get("entries") or {}).values())
    lat = [int(e.get("latency_ms", 0)) for e in entries if e.get("latency_ms")]
    tokens = [int(((e.get("raw") or {}).get("usage") or {}).get("input_tokens", 0))
              for e in entries]
    tokens = [t for t in tokens if t]
    out: dict[str, Any] = {"recorded_calls": len(entries), "synthetic": bool(data.get("synthetic"))}
    if lat:
        out["latency_ms_median"] = statistics.median(lat)
        out["latency_ms_p90"] = sorted(lat)[int(0.9 * (len(lat) - 1))]
    if tokens:
        med = statistics.median(tokens)
        out["input_tokens_median"] = med
        out["cost_usd_per_candidate_median"] = med * JEV_PRICE_PER_MILLION_INPUT / 1e6
    return out


def metrics(policy: Policy, cases: list[EvalCase], judge_name: str, model: str | None,
            fixture_path: Path | None = None) -> dict[str, Any]:
    """All headline numbers for one policy's contrast-pair run."""
    by_cat: dict[str, list[EvalCase]] = defaultdict(list)
    groups: dict[str, list[EvalCase]] = defaultdict(list)
    for c in cases:
        by_cat[c.pair.category].append(c)
        groups[c.pair.pair_id].append(c)
    pair_ok = [all(c.correct for c in g) for g in groups.values() if len(g) > 1]
    categories = {}
    for cat, cs in sorted(by_cat.items()):
        cat_groups = [g for g in groups.values() if g[0].pair.category == cat and len(g) > 1]
        categories[cat] = {
            "n": len(cs), "accuracy": sum(c.correct for c in cs) / len(cs),
            "pair_consistency": (sum(all(c.correct for c in g) for g in cat_groups)
                                 / len(cat_groups)) if cat_groups else None,
        }
    confusion = Counter(f"{'/'.join(c.pair.test.expected)} -> {c.decision.action}"
                        for c in cases)
    failures = [{"input": c.pair.test.input, "category": c.pair.category,
                 "expected": c.pair.test.expect, "got": c.decision.action,
                 "rule": c.decision.rule, "type": c.decision.type,
                 "error": c.decision.error} for c in cases if not c.correct]
    return {
        "policy": policy.name, "policy_version": policy.version, "judge": judge_name,
        "model": model, "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases), "pairs": len(pair_ok),
        "accuracy": sum(c.correct for c in cases) / len(cases) if cases else None,
        "pair_consistency": sum(pair_ok) / len(pair_ok) if pair_ok else None,
        "judge_errors": sum(1 for c in cases if c.decision.error),
        "categories": categories, "confusion": dict(sorted(confusion.items())),
        "calibration": calibration(cases), "calls": fixture_stats(fixture_path),
        "failures": failures,
    }


def write_plots(result: dict[str, Any], out_dir: Path) -> list[Path]:
    """Accuracy-by-category bars and reliability curves (needs matplotlib)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover
        return []
    paths = []
    cats = result["categories"]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(cats) + 1.5))
    names = list(cats)
    ax.barh(names, [cats[n]["accuracy"] for n in names], color="#4a7bd0")
    ax.axvline(0.9, color="#999", linestyle="--", linewidth=1)
    ax.set_xlim(0, 1)
    ax.set_xlabel("action accuracy")
    ax.set_title(f"{result['policy']} v{result['policy_version']} contrast pairs "
                 f"({result['model']})")
    fig.tight_layout()
    p = out_dir / "accuracy_by_category.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)
    for name, cal in result["calibration"].items():
        fig, ax = plt.subplots(figsize=(4.5, 4.5))
        ax.plot([0, 1], [0, 1], color="#bbb", linewidth=1)
        for key, label, color in (("reliability_before", "raw", "#d0664a"),
                                  ("reliability_after_cv", "temperature-scaled (CV)",
                                   "#4a7bd0")):
            pts = cal[key]
            score = cal["ece_before" if key.endswith("before") else "ece_after_cv"]
            ax.plot([b["confidence"] for b in pts], [b["accuracy"] for b in pts], marker="o",
                    label=f"{label}, ECE {score:.3f}", color=color)
        ax.set_xlabel("predicted probability")
        ax.set_ylabel("observed rate")
        ax.set_title(f"{name} (n={cal['n']})")
        ax.legend(fontsize=8)
        fig.tight_layout()
        p = out_dir / f"calibration_{name}.png"
        fig.savefig(p, dpi=120)
        plt.close(fig)
        paths.append(p)
    return paths
