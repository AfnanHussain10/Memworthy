"""Review queue: decisions routed to ``review`` (or errors) and their resolutions.

Resolutions live next to the ledger in ``<ledger>.reviews.jsonl`` so the ledger itself stays
append-only and replayable. Overrides can be exported as policy tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import yaml

from memworthy.models import Action, Decision, utcnow

Resolution = Literal["accepted", "overridden"]


def reviews_path(ledger: str | Path) -> Path:
    """Sidecar file holding review resolutions for a ledger."""
    p = Path(ledger)
    return p.with_name(p.name + ".reviews.jsonl")


def load_resolutions(ledger: str | Path) -> dict[str, dict[str, Any]]:
    """Resolutions by decision id (the latest one wins)."""
    path = reviews_path(ledger)
    out: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                out[str(rec["decision_id"])] = rec
    return out


def pending(decisions: Iterable[Decision], ledger: str | Path) -> list[Decision]:
    """Decisions needing a person: action ``review`` or a judge/store error, unresolved."""
    done = load_resolutions(ledger)
    return [d for d in decisions
            if (d.action == "review" or d.error) and d.id not in done]


def resolve(ledger: str | Path, decision: Decision, resolution: Resolution,
            action: Action) -> dict[str, Any]:
    """Append a resolution for one decision."""
    rec = {"decision_id": decision.id, "resolution": resolution, "action": action,
           "at": utcnow().isoformat()}
    with reviews_path(ledger).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def as_test(decision: Decision, action: Action) -> dict[str, Any]:
    """A policy test (YAML-ready dict) capturing a human override."""
    c = decision.candidate
    test: dict[str, Any] = {"input": c.text}
    if c.source.role != "user":
        test["role"] = c.source.role
    if c.subject != "user":
        test["subject"] = c.subject
    if c.context:
        test["context"] = c.context
    if c.source.text and c.source.text != c.text:
        test["source_text"] = c.source.text
    if decision.target is not None:
        test["existing"] = [decision.target.text]
    test["expect"] = action
    return test


def export_tests(path: str | Path, tests: list[dict[str, Any]]) -> None:
    """Append tests to a YAML list file (created if missing)."""
    p = Path(path)
    existing = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None
    items = list(existing or []) + tests
    p.write_text(yaml.safe_dump(items, sort_keys=False, allow_unicode=True, width=100),
                 encoding="utf-8")
