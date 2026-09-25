"""MemGate command-line interface. The only module allowed to print."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import typer

from memgate import __version__
from memgate.judges.base import Judge, JudgeError
from memgate.judges.mock import MockJudge
from memgate.judges.recorded import FixtureFile, RecordedJudge, bundled_fixture_path
from memgate.pairs import PairError, bundled_pairs_path, load_pairs
from memgate.policy.loader import Policy, PolicyError, load_policy
from memgate.policy.schema import PolicyTest
from memgate.testing import TestResult, run_tests

app = typer.Typer(help="MemGate: decide what an AI system should remember.",
                  no_args_is_help=True, add_completion=False)
JUDGES = ("mock", "recorded", "jev")


def load_env() -> None:
    """Load .env from the working directory if python-dotenv is installed (dev extra)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env", override=False)


def fail(message: str, code: int = 1) -> typer.Exit:
    """Print an error to stderr and return an Exit to raise."""
    print(f"error: {message}", file=sys.stderr)
    return typer.Exit(code)


def get_policy(ref: str) -> Policy:
    """Load a policy or exit with its error."""
    try:
        return load_policy(ref)
    except PolicyError as exc:
        raise fail(str(exc)) from None


def fixtures_for(policy: Policy, fixtures: Path | None) -> Path:
    """The fixture file to use: explicit, else the bundled one for a template."""
    if fixtures is not None:
        return fixtures
    bundled = bundled_fixture_path(policy.name)
    if bundled is None:
        raise fail(f"no bundled fixtures for '{policy.name}'; pass --fixtures PATH")
    return bundled


def make_judge(kind: str, policy: Policy, fixtures: Path | None) -> Judge:
    """Build the judge selected on the command line."""
    if kind not in JUDGES:
        raise fail(f"--judge must be one of {', '.join(JUDGES)}")
    if kind == "mock":
        return MockJudge()
    if kind == "recorded":
        path = fixtures_for(policy, fixtures)
        judge = RecordedJudge(path)
        if judge.synthetic:
            print("warning: fixtures are synthetic (hand-authored); results are not "
                  "evidence of real judge behavior", file=sys.stderr)
        return judge
    from memgate.judges.jev import JevJudge

    try:
        return JevJudge()
    except JudgeError as exc:
        raise fail(str(exc)) from None


def _signal_summary(result: TestResult) -> str:
    parts = []
    for name, sig in result.decision.signals.items():
        if sig is None:
            continue
        if isinstance(sig.value, float):
            parts.append(f"{name}={sig.value:.2f}")
        else:
            parts.append(f"{name}={sig.value}")
    return ", ".join(parts)


def result_json(r: TestResult) -> dict[str, Any]:
    """JSON form of a test result."""
    return {
        "index": r.index, "input": r.test.input, "expect": r.test.expect,
        "expect_type": r.test.expect_type, "action": r.decision.action,
        "type": r.decision.type, "rule": r.decision.rule, "passed": r.passed,
        "reason": r.reason, "error": r.decision.error,
        "signals": {k: (v.model_dump(mode="json") if v else None)
                    for k, v in r.decision.signals.items()},
    }


@app.command()
def version() -> None:
    """Print the MemGate version."""
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
            if r.passed:
                continue
            print(f"FAIL [{r.index}] {r.test.input!r}: {r.reason} (rule {r.decision.rule})")
            print(f"     type={r.decision.type}; {_signal_summary(r)}")
        rate = 100.0 * passed / len(results)
        print(f"{pol.name} v{pol.version}: {passed}/{len(results)} passed ({rate:.1f}%) "
              f"with judge={j.name}")
    if passed != len(results):
        raise typer.Exit(1)


@app.command()
def record(
    policy: str = typer.Argument(..., help="Template name or policy file"),
    input: str = typer.Argument("tests", help="'tests', 'pairs', a pair .yaml, a chat "
                                "script .chat.json, or a candidates .json/.jsonl file"),
    out: Path | None = typer.Option(None, help="Fixture file (default: bundled path)"),
    fresh: bool = typer.Option(False, help="Drop existing entries before recording"),
) -> None:
    """Make live Jev calls and write RecordedJudge fixtures."""
    load_env()
    from memgate.judges.jev import JevJudge
    from memgate.judges.recorded import RecordingJudge

    pol = get_policy(policy)
    path = out or bundled_fixture_path(pol.name) or _default_fixture_path(pol)
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


def _default_fixture_path(pol: Policy) -> Path:
    from importlib import resources

    return Path(str(resources.files("memgate"))) / "templates" / "fixtures" / f"{pol.name}.json"


async def _record(pol: Policy, recorder: Judge, input: str) -> int:
    from memgate.gate import Gate
    from memgate.ledger import MemoryLedger
    from memgate.sources.candidates import load_candidates
    from memgate.stores.dict import DictStore

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
    if input.endswith(".chat.json"):
        messages = json.loads(Path(input).read_text(encoding="utf-8"))
        gate = Gate(pol, DictStore(), judge=recorder, ledger=MemoryLedger())
        decisions = await gate.aingest_messages(messages)
        return sum(1 for d in decisions if d.error)
    gate = Gate(pol, DictStore(), judge=recorder, ledger=MemoryLedger())
    decisions = await gate.aevaluate(load_candidates(input))
    return sum(1 for d in decisions if d.error)


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
