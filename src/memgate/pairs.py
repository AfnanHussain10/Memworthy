"""Contrast-pair files: templates whose one changed word flips the correct action."""

from __future__ import annotations

import itertools
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from memgate.policy.schema import PolicyTest

CASE_FIELDS = ("role", "subject", "context", "existing", "metadata", "expect_type")


class PairError(Exception):
    """A pair file is malformed."""


@dataclass(frozen=True)
class PairCase:
    """One generated test with the pair it belongs to."""

    test: PolicyTest
    pair_id: str
    category: str
    template: int


def _fields(template: str) -> list[str]:
    return [f for _, f, _, _ in string.Formatter().parse(template) if f]


def _fmt(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format(**values)
    if isinstance(value, list):
        return [_fmt(v, values) for v in value]
    if isinstance(value, dict):
        return {k: _fmt(v, values) for k, v in value.items()}
    return value


def expand_pairs(items: list[dict[str, Any]], source: str = "<pairs>") -> list[PairCase]:
    """Expand pair templates into tests; each fill combination forms one pair group."""
    out: list[PairCase] = []
    for ti, item in enumerate(items):
        if not isinstance(item, dict) or "template" not in item or "cases" not in item:
            raise PairError(f"{source}: item {ti} needs 'template' and 'cases'")
        template = str(item["template"])
        fills: dict[str, list[str]] = {k: [str(x) for x in v]
                                       for k, v in (item.get("fills") or {}).items()}
        category = str(item.get("category", f"template_{ti}"))
        keys = list(fills)
        for combo in itertools.product(*(fills[k] for k in keys)):
            base = dict(zip(keys, combo, strict=True))
            pair_id = f"{ti}:" + "|".join(combo)
            for case in item["cases"]:
                values = {**base, **{k: str(v) for k, v in case.items()
                                     if k not in ("expect", *CASE_FIELDS)}}
                missing = [f for f in _fields(template) if f not in values]
                if missing:
                    raise PairError(f"{source}: template {ti} has no value for {missing}")
                fields: dict[str, Any] = {"input": template.format(**values),
                                          "expect": case["expect"]}
                for f in CASE_FIELDS:
                    if f in case or f in item:
                        fields[f] = _fmt(case.get(f, item.get(f)), values)
                out.append(PairCase(PolicyTest.model_validate(fields), pair_id, category, ti))
    return out


def load_pairs(path: str | Path) -> list[PairCase]:
    """Load and expand a pair file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise PairError(f"{path}: pair file must be a YAML list")
    return expand_pairs(data, str(path))


def bundled_pairs_path(policy: str) -> Path | None:
    """Path of the bundled pair file for a template policy, if any."""
    from importlib import resources

    p = resources.files("memgate") / "templates" / "pairs" / f"{policy}.yaml"
    return Path(str(p)) if p.is_file() else None
