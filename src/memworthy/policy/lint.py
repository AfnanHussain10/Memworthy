"""Policy lint: warnings about policies that load but are likely to behave badly."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass

from memworthy.policy.expr import BoolOp, Compare, Lit, Name, Node, Not, parse
from memworthy.policy.loader import CONFLICT_ACTIONS, Policy
from memworthy.policy.schema import ModelSignal

MAX_TYPES = 12
OVERLAP = 0.5
VAGUE_WORDS = frozenset({"good", "bad", "relevant", "important", "useful", "interesting",
                         "appropriate", "valuable", "significant", "ok"})
STOP = frozenset("a an the of or and to in on for with is are this that it its as by be not "
                 "such".split())


@dataclass(frozen=True)
class LintWarning:
    """One lint finding."""

    code: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{where}[{self.code}] {self.message}"


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of content words."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def _names(node: Node) -> set[str]:
    if isinstance(node, Name):
        return {node.parts[0]}
    if isinstance(node, Not):
        return _names(node.operand)
    if isinstance(node, BoolOp):
        return set().union(*(_names(o) for o in node.operands))
    if isinstance(node, Compare):
        return _names(node.left) | _names(node.right)
    return set()


def _prob_compares(node: Node, probs: set[str]) -> list[tuple[str, str, float]]:
    """(name, op, literal) comparisons of probability-valued names against numbers."""
    if isinstance(node, Not):
        return _prob_compares(node.operand, probs)
    if isinstance(node, BoolOp):
        return [c for o in node.operands for c in _prob_compares(o, probs)]
    if isinstance(node, Compare) and isinstance(node.left, Name) and \
            isinstance(node.right, Lit) and isinstance(node.right.value, (int, float)) and \
            not isinstance(node.right.value, bool):
        name = ".".join(node.left.parts)
        if name in probs:
            return [(name, node.op, float(node.right.value))]
    return []


def lint(policy: Policy) -> list[LintWarning]:
    """Return warnings for a loaded policy (an empty list means clean)."""
    spec = policy.spec
    out: list[LintWarning] = []
    types = spec.types
    if len(types) > MAX_TYPES:
        out.append(LintWarning("too-many-types", f"{len(types)} types; above {MAX_TYPES} the "
                               "type question gets unreliable", policy.line_of(("types",))))
    for (a, da), (b, db) in itertools.combinations(types.items(), 2):
        sim = similarity(da, db)
        if sim >= OVERLAP:
            out.append(LintWarning("overlapping-types", f"types '{a}' and '{b}' have overlapping "
                                   f"descriptions (similarity {sim:.2f})",
                                   policy.line_of(("types", b))))
    has_py = any(r.py for r in policy.rules)
    used: set[str] = set()
    for r in policy.rules:
        if r.expr is not None:
            used |= r.expr.roots
    if not has_py:
        for name in spec.signals:
            if name not in used:
                out.append(LintWarning("unused-signal", f"signal '{name}' is not used by any rule",
                                       policy.line_of(("signals", name))))
    probs = {n for n, s in policy.model_signals.items() if s.kind == "noul"}
    probs |= {f"{n}.p" for n in policy.model_signals} | {"conflict.p"}
    probs |= {f"{n}.{o}" for n, s in policy.model_signals.items()
              if s.kind == "choice" for o in s.options or {}}
    seen: dict[str, int] = {}
    for r in policy.rules:
        line = r.line
        when = r.rule.when
        if when is None:
            continue
        key = " ".join(when.split())
        if key in seen:
            out.append(LintWarning("unreachable-rule", f"rule '{r.id}' repeats the condition of "
                                   f"rules[{seen[key]}] and can never fire", line))
        seen.setdefault(key, r.index)
        if r.py:
            continue
        tree = parse(when)
        if isinstance(tree, Lit):
            msg = "is always true; later rules are unreachable" if tree.value else \
                "is always false and never fires"
            out.append(LintWarning("constant-rule", f"rule '{r.id}' {msg}", line))
        for name, op, value in _prob_compares(tree, probs):
            if (op in (">", ">=") and value >= 1.0 and not (op == ">=" and value == 1.0)) or \
                    (op in ("<", "<=") and value <= 0.0 and not (op == "<=" and value == 0.0)):
                out.append(LintWarning("impossible-threshold", f"rule '{r.id}': "
                                       f"'{name} {op} {value}' can never hold for a probability",
                                       line))
    for name, sig in spec.signals.items():
        if isinstance(sig, ModelSignal):
            out += _prompt_warnings(policy, name, sig.prompt)
    if spec.conflict.enabled and not any(r.rule.then in CONFLICT_ACTIONS for r in policy.rules) \
            and "conflict" not in used:
        out.append(LintWarning("unused-conflict", "conflict is enabled but no rule updates, "
                               "merges or supersedes, so no shortlist is ever built",
                               policy.line_of(("conflict",))))
    return out


def _prompt_warnings(policy: Policy, name: str, prompt: str) -> list[LintWarning]:
    line = policy.line_of(("signals", name))
    words = prompt.split()
    out = []
    if len(words) < 4:
        out.append(LintWarning("vague-prompt", f"signal '{name}': prompt is very short", line))
    if not prompt.strip().endswith("?"):
        out.append(LintWarning("vague-prompt", f"signal '{name}': prompt is not a question",
                               line))
    vague = sorted(VAGUE_WORDS & {w.strip("?,.").lower() for w in words})
    if vague:
        out.append(LintWarning("vague-prompt", f"signal '{name}': vague wording "
                               f"({', '.join(vague)}); say what makes it so", line))
    return out
