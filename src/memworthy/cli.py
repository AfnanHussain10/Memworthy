"""Memworthy command-line interface. The CLI layer is the only code allowed to print."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import typer

from memworthy import __version__
from memworthy.cli_support import (
    default_fixture_path,
    detect_source,
    fail,
    get_policy,
    load_candidates_file,
    load_chat,
    load_env,
    make_judge,
    make_store,
    result_json,
    signal_summary,
)
from memworthy.judges.base import Judge, JudgeError
from memworthy.judges.recorded import FixtureFile, bundled_fixture_path
from memworthy.pairs import PairError, bundled_pairs_path, load_pairs
from memworthy.policy.loader import Policy
from memworthy.policy.schema import PolicyTest
from memworthy.testing import run_tests

app = typer.Typer(help="Memworthy: decide what an AI system should remember.",
                  no_args_is_help=True, add_completion=False)


@app.command()
def version() -> None:
    """Print the Memworthy version."""
    print(__version__)


@app.command("test")
def test_cmd(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    judge: str = typer.Option("recorded", help="mock, recorded or jev"),
    fixtures: Path | None = typer.Option(None, help="RecordedJudge fixture file"),
    pairs: Path | None = typer.Option(None, help="Run a contrast-pair file instead of tests"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Run a policy's tests; exit 1 if any fail."""
    load_env()
    pol = get_policy(policy)
    tests: list[PolicyTest] = list(pol.spec.tests)
    if pairs is not None:
        try:
            tests = [c.test for c in load_pairs(pairs)]
        except (PairError, OSError) as exc:
            raise fail(str(exc)) from None
    if not tests:
        raise fail(f"policy '{pol.name}' has no tests")
    j = make_judge(judge, pol, fixtures)
    results = asyncio.run(run_tests(pol, j, tests))
    passed = sum(r.passed for r in results)
    if as_json:
        print(json.dumps({"policy": pol.name, "version": pol.version, "judge": j.name,
                          "passed": passed, "total": len(results),
                          "results": [result_json(r) for r in results]}, indent=1))
    else:
        for r in results:
            if not r.passed:
                print(f"FAIL [{r.index}] {r.test.input!r}: {r.reason} (rule {r.decision.rule})")
                print(f"     type={r.decision.type}; {signal_summary(r)}")
        rate = 100.0 * passed / len(results)
        print(f"{pol.name} v{pol.version}: {passed}/{len(results)} passed ({rate:.1f}%) "
              f"with judge={j.name}")
    if passed != len(results):
        raise typer.Exit(1)


@app.command()
def run(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    source: Path = typer.Argument(..., help="Candidates file, chat JSON or session folder"),
    fmt: str = typer.Option("auto", "--format",
                            help="candidates, chat, claude_code, codex or auto"),
    store: str = typer.Option("dict", help="dict, markdown:PATH or mem0"),
    judge: str = typer.Option("jev", help="jev, recorded or mock"),
    fixtures: Path | None = typer.Option(None, help="Fixture file for --judge recorded"),
    extractor: str = typer.Option("none", help="none or llm (OpenRouter, EXTRACTOR_MODEL)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Decide only; write nothing"),
    ledger: Path | None = typer.Option(None, help="Ledger path (default MEMWORTHY_LEDGER or "
                                       "memworthy.ledger.jsonl)"),
) -> None:
    """Gate a source into a store and print a summary."""
    load_env()
    from memworthy.gate import Gate
    from memworthy.ledger import JsonlLedger

    pol = get_policy(policy)
    if not source.exists():
        raise fail(f"source not found: {source}")
    kind = detect_source(source, fmt)
    j = make_judge(judge, pol, fixtures)
    ext = None
    if extractor == "llm":
        from memworthy.extractors import openrouter_extractor_from_env

        try:
            ext = openrouter_extractor_from_env()
        except RuntimeError as exc:
            raise fail(str(exc)) from None
    elif extractor != "none":
        raise fail("--extractor must be none or llm")
    gate = Gate(pol, make_store(store), judge=j, ledger=JsonlLedger(ledger), extractor=ext,
                apply=not dry_run)
    report = asyncio.run(_run(gate, source, kind))
    decisions = report.pop("decisions")
    for key, value in report.items():
        print(f"{key}: {value}")
    counts = Counter(d.action for d in decisions)
    print("decisions: " + (", ".join(f"{a}={n}" for a, n in sorted(counts.items())) or "none"))
    errors = [d for d in decisions if d.error]
    if errors:
        print(f"{len(errors)} decisions had errors (first: {errors[0].error})", file=sys.stderr)
    print(f"ledger: {gate.ledger.path if hasattr(gate.ledger, 'path') else '-'}")


async def _run(gate: Any, source: Path, kind: str) -> dict[str, Any]:
    if kind in ("sessions", "claude_code", "codex"):
        from memworthy.sources.pipeline import ingest_sessions

        fmt = "auto" if kind == "sessions" else kind
        ing = await ingest_sessions(gate.policy, gate.judge, source, fmt, gate.extractor)
        decisions = await gate.aevaluate(ing.candidates)
        return {"sessions": len(ing.sessions), "episodes": len(ing.episodes),
                "noise_dropped": len(ing.dropped), "candidates": len(ing.candidates),
                "decisions": decisions}
    if kind == "chat":
        return {"decisions": await gate.aingest_messages(load_chat(source))}
    return {"decisions": await gate.aevaluate(load_candidates_file(source))}


@app.command()
def record(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    input: str = typer.Argument("tests", help="'tests', 'pairs', a pair .yaml, a chat "
                                ".chat.json, a session folder, or a candidates file"),
    out: Path | None = typer.Option(None, help="Fixture file (default: bundled path)"),
    fresh: bool = typer.Option(False, help="Drop existing entries before recording"),
) -> None:
    """Make live Jev calls and write RecordedJudge fixtures."""
    load_env()
    from memworthy.judges.jev import JevJudge
    from memworthy.judges.recorded import RecordingJudge

    pol = get_policy(policy)
    path = out or bundled_fixture_path(pol.name) or default_fixture_path(pol)
    try:
        live = JevJudge()
    except JudgeError as exc:
        raise fail(str(exc)) from None
    recorder = RecordingJudge(live, FixtureFile(path))
    if fresh:
        recorder.fixtures.entries = {}
    before = len(recorder.fixtures.entries)
    try:
        errors = asyncio.run(_record(pol, recorder, input))
    finally:
        recorder.fixtures.save()
    print(f"recorded {recorder.recorded} new answers ({before} existing) into {path}")
    if errors:
        print(f"{errors} candidates failed to record (judge errors)", file=sys.stderr)
        raise typer.Exit(1)


async def _record(pol: Policy, recorder: Judge, input: str) -> int:
    from memworthy.gate import Gate
    from memworthy.ledger import MemoryLedger
    from memworthy.stores.dict import DictStore

    if input in ("tests", "pairs") or input.endswith((".yaml", ".yml")):
        if input == "tests":
            tests = list(pol.spec.tests)
        else:
            pair_path = bundled_pairs_path(pol.name) if input == "pairs" else Path(input)
            if pair_path is None:
                raise fail(f"no bundled pairs for '{pol.name}'")
            tests = [c.test for c in load_pairs(pair_path)]
        results = await run_tests(pol, recorder, tests)
        return sum(1 for r in results if r.decision.error)
    gate = Gate(pol, DictStore(), judge=recorder, ledger=MemoryLedger())
    path = Path(input)
    kind = detect_source(path, "auto")
    report = await _run(gate, path, kind)
    return sum(1 for d in report["decisions"] if d.error)


@app.command()
def replay(
    ledger: Path = typer.Argument(..., help="Ledger JSONL written by Memworthy"),
    policy: str = typer.Argument(..., help="New policy (template name or file)"),
    only_changed: bool = typer.Option(False, "--only-changed", help="List changes only"),
    fixtures: Path | None = typer.Option(None, help="Recorded answers for re-judging"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Re-decide past decisions under a new policy and list what would change."""
    load_env()
    from memworthy.judges.recorded import RecordedJudge
    from memworthy.ledger import JsonlLedger, LedgerError
    from memworthy.replay import replay as do_replay

    pol = get_policy(policy)
    try:
        decisions = list(JsonlLedger(ledger).read())
    except (LedgerError, OSError) as exc:
        raise fail(str(exc)) from None
    judge = RecordedJudge(fixtures) if fixtures is not None else None
    results = asyncio.run(do_replay(pol, decisions, judge))
    shown = [r for r in results if r.changed or not only_changed]
    if as_json:
        print(json.dumps([{"decision_id": r.old.id, "text": r.old.candidate.text,
                           "old_action": r.old.action,
                           "new_action": r.new.action if r.new else None,
                           "new_rule": r.new.rule if r.new else None, "changed": r.changed,
                           "method": r.method, "reason": r.reason} for r in shown], indent=1))
        return
    for r in shown:
        if r.new is None:
            print(f"NEEDS-LIVE {r.old.action:13} {r.old.candidate.text[:70]!r} ({r.reason})")
        elif r.changed:
            print(f"CHANGED    {r.old.action} -> {r.new.action} (rule {r.new.rule}) "
                  f"{r.old.candidate.text[:70]!r}")
        else:
            print(f"same       {r.old.action:13} {r.old.candidate.text[:70]!r}")
    counts = Counter("changed" if r.changed else r.method if r.new is None else "same"
                     for r in results)
    print(f"{len(results)} decisions: {counts['changed']} changed, {counts['same']} unchanged, "
          f"{counts['needs_live']} need live calls")


@app.command()
def lint(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    strict: bool = typer.Option(False, "--strict", help="Warnings become errors"),
) -> None:
    """Warn about overlapping types, unused signals, unreachable rules and vague prompts."""
    from memworthy.policy.lint import lint as do_lint

    pol = get_policy(policy)
    warnings = do_lint(pol)
    for w in warnings:
        print(f"{pol.source}: {w}")
    print(f"{pol.name} v{pol.version}: {len(warnings)} warning(s)")
    if strict and warnings:
        raise typer.Exit(1)


@app.command()
def review(
    ledger: Path = typer.Argument(..., help="Ledger JSONL written by Memworthy"),
    export_tests: Path | None = typer.Option(None, "--export-tests",
                                             help="Append overrides as policy tests"),
) -> None:
    """Accept, override or skip queued review decisions, one at a time."""
    from memworthy.ledger import JsonlLedger, LedgerError
    from memworthy.models import ACTIONS
    from memworthy.review import as_test, pending, resolve
    from memworthy.review import export_tests as write_tests

    try:
        queue = pending(JsonlLedger(ledger).read(), ledger)
    except (LedgerError, OSError) as exc:
        raise fail(str(exc)) from None
    print(f"{len(queue)} decision(s) to review")
    new_tests = []
    for d in queue:
        sigs = ", ".join(f"{k}={v.value:.2f}" if isinstance(v.value, float) else f"{k}={v.value}"
                         for k, v in d.signals.items() if v is not None)
        print(f"\n{d.candidate.text!r}\n  action={d.action} rule={d.rule} type={d.type}"
              f"{' error=' + d.error if d.error else ''}\n  {sigs}")
        choice = typer.prompt("[a]ccept, [o]verride, [s]kip", default="s").strip().lower()
        if choice.startswith("a"):
            resolve(ledger, d, "accepted", d.action)
        elif choice.startswith("o"):
            action = typer.prompt(f"correct action ({', '.join(ACTIONS)})").strip()
            if action not in ACTIONS:
                print(f"unknown action {action!r}; skipped")
                continue
            resolve(ledger, d, "overridden", action)
            new_tests.append(as_test(d, action))
    if export_tests is not None and new_tests:
        write_tests(export_tests, new_tests)
        print(f"exported {len(new_tests)} test(s) to {export_tests}")


@app.command("eval")
def eval_cmd(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    pairs: Path | None = typer.Option(None, help="Pair file (default: the bundled one)"),
    judge: str = typer.Option("recorded", help="recorded or jev"),
    fixtures: Path | None = typer.Option(None, help="Fixture file for --judge recorded"),
    out: Path = typer.Option(Path("eval/results"), help="Output folder"),
) -> None:
    """Run contrast pairs and write metrics JSON, a summary and plots."""
    load_env()
    from memworthy.evaluation import metrics, run_pairs, write_plots
    from memworthy.judges.recorded import bundled_fixture_path as fixture_path
    from memworthy.reporting import summary_markdown

    pol = get_policy(policy)
    pair_path = pairs or bundled_pairs_path(pol.name)
    if pair_path is None:
        raise fail(f"no bundled pairs for '{pol.name}'; pass --pairs")
    cases = load_pairs(pair_path)
    j = make_judge(judge, pol, fixtures)
    evals = asyncio.run(run_pairs(pol, j, cases))
    fx = (fixtures or fixture_path(pol.name)) if judge == "recorded" else None
    model = next((c.decision.model for c in evals if c.decision.model), None)
    result = metrics(pol, evals, j.name, model, fx)
    result["pairs_file"] = str(pair_path.name)
    dest = out / pol.name
    dest.mkdir(parents=True, exist_ok=True)
    if result["calls"].get("synthetic"):
        print("warning: synthetic fixtures; these numbers are not evidence and must not be "
              "reported", file=sys.stderr)
    (dest / "metrics.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    (dest / "summary.md").write_text(summary_markdown(result), encoding="utf-8")
    plots = write_plots(result, dest)
    print(f"{pol.name} v{pol.version} on {result['cases']} cases ({model}): accuracy "
          f"{result['accuracy']:.3f}, pair consistency {result['pair_consistency']:.3f}, "
          f"judge errors {result['judge_errors']}")
    print(f"wrote {dest / 'metrics.json'}, {dest / 'summary.md'} and {len(plots)} plot(s)")


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
