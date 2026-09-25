"""Render evaluation results as Markdown (used by `memgate eval` and the README)."""

from __future__ import annotations

from typing import Any


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def summary_markdown(r: dict[str, Any]) -> str:
    """A short, honest Markdown report of one policy's contrast-pair run."""
    calls = r.get("calls", {})
    lines = [
        f"# {r['policy']} v{r['policy_version']}: contrast-pair evaluation", "",
        f"Judge `{r['judge']}`, model `{r['model']}`, {r['cases']} cases in {r['pairs']} pairs "
        f"(`{r.get('pairs_file', '')}`), generated {r['generated_at'][:10]}.", "",
    ]
    if calls.get("synthetic"):
        lines += ["**Synthetic fixtures: these numbers are not evidence.**", ""]
    lines += [
        "| Metric | Value |", "| --- | --- |",
        f"| Action accuracy | {_pct(r['accuracy'])} |",
        f"| Pair consistency | {_pct(r['pair_consistency'])} |",
        f"| Judge errors | {r['judge_errors']} |",
    ]
    if "latency_ms_median" in calls:
        med, p90 = calls["latency_ms_median"], calls["latency_ms_p90"]
        lines.append(f"| Median Jev call latency (at recording) | {med:.0f} ms "
                     f"(p90 {p90:.0f} ms) |")
    if "cost_usd_per_candidate_median" in calls:
        lines.append(f"| Median input tokens / cost per candidate | "
                     f"{calls['input_tokens_median']:.0f} / "
                     f"${calls['cost_usd_per_candidate_median']:.6f} |")
    lines += ["", "## By category", "", "| Category | Cases | Accuracy | Pair consistency |",
              "| --- | --- | --- | --- |"]
    for cat, c in r["categories"].items():
        lines.append(f"| {cat} | {c['n']} | {_pct(c['accuracy'])} | "
                     f"{_pct(c['pair_consistency'])} |")
    if r["calibration"]:
        lines += ["", "## Calibration", "",
                  "| Signal | n | ECE raw | ECE temperature-scaled (2-fold CV) | T (all data) |",
                  "| --- | --- | --- | --- | --- |"]
        for name, c in r["calibration"].items():
            lines.append(f"| {name} | {c['n']} | {c['ece_before']:.3f} | "
                         f"{c['ece_after_cv']:.3f} | {c['temperature_all']:.2f} |")
        lines += ["", "Labels are the template's expected action for categories where the named "
                  "signal decides the case. A fitted temperature well below 1 means the raw "
                  "probabilities are under-confident but on the correct side of 0.5; scaling "
                  "then pushes them towards 0 or 1, so a near-zero scaled ECE shows the signal "
                  "separates these cases at 0.5, not that its probabilities are finely "
                  "calibrated. Sample sizes are small; see `n`."]
    lines += ["", "## Failures", ""]
    if not r["failures"]:
        lines.append("None.")
    for f in r["failures"]:
        exp = f["expected"] if isinstance(f["expected"], str) else "/".join(f["expected"])
        lines.append(f"- `{f['category']}`: \"{f['input']}\": expected {exp}, got "
                     f"{f['got']} (rule `{f['rule']}`, type `{f['type']}`)")
    return "\n".join(lines) + "\n"
