"""Helpers for the CLI (part of the CLI layer: allowed to print and to load .env)."""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import typer

from memworthy.judges.base import Judge, JudgeError
from memworthy.judges.mock import MockJudge
from memworthy.judges.recorded import RecordedJudge, bundled_fixture_path
from memworthy.models import Candidate
from memworthy.policy.loader import Policy, PolicyError, load_policy
from memworthy.sources.session import detect_format, read_jsonl
from memworthy.stores.base import MemoryStore
from memworthy.testing import TestResult

JUDGES = ("mock", "recorded", "jev")
FORMATS = ("candidates", "chat", "claude_code", "codex", "auto")


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


def default_fixture_path(policy: Policy) -> Path:
    """Where fixtures for a policy go by default (bundled location)."""
    root = Path(str(resources.files("memworthy"))) / "templates" / "fixtures"
    return root / f"{policy.name}.json"


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
        judge = RecordedJudge(fixtures_for(policy, fixtures))
        if judge.synthetic:
            print("warning: fixtures are synthetic (hand-authored); results are not "
                  "evidence of real judge behavior", file=sys.stderr)
        return judge
    from memworthy.judges.jev import JevJudge

    try:
        return JevJudge()
    except JudgeError as exc:
        raise fail(str(exc)) from None


def make_store(spec: str) -> MemoryStore:
    """Build a store from ``dict``, ``markdown:PATH`` or ``mem0``."""
    if spec == "dict":
        from memworthy.stores.dict import DictStore

        return DictStore()
    if spec.startswith("markdown:"):
        from memworthy.stores.markdown import MarkdownStore

        return MarkdownStore(spec.split(":", 1)[1])
    if spec == "mem0":
        import importlib

        try:
            module = importlib.import_module("memworthy.stores.mem0")
        except ImportError as exc:
            raise fail(f"mem0 store needs `pip install \"memworthy[mem0]\"` ({exc})") from None
        store: MemoryStore = module.Mem0Store.from_env()
        return store
    raise fail("--store must be dict, markdown:PATH or mem0")


def detect_source(path: Path, fmt: str) -> str:
    """Resolve ``auto`` to a concrete source format."""
    if fmt not in FORMATS:
        raise fail(f"--format must be one of {', '.join(FORMATS)}")
    if fmt != "auto":
        return fmt
    if path.is_dir():
        return "sessions"
    if path.suffix == ".jsonl" and detect_format(read_jsonl(path)) is not None:
        return "sessions"
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and data and all(
                isinstance(d, dict) and "role" in d and "content" in d for d in data):
            return "chat"
    return "candidates"


def load_chat(path: Path) -> list[dict[str, Any]]:
    """Read a chat transcript: a JSON list of {role, content} messages."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise fail(f"{path}: chat source must be a JSON list of messages")
    return [d for d in data if isinstance(d, dict)]


def load_candidates_file(path: Path) -> list[Candidate]:
    """Read a candidates JSON or JSONL file."""
    from memworthy.sources.candidates import load_candidates

    return load_candidates(path)


def signal_summary(result: TestResult) -> str:
    """Short ``name=value`` list of a result's evaluated signals."""
    parts = []
    for name, sig in result.decision.signals.items():
        if sig is None:
            continue
        value = f"{sig.value:.2f}" if isinstance(sig.value, float) else str(sig.value)
        parts.append(f"{name}={value}")
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
