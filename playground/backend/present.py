"""Shape decisions and memories for the playground UI."""

from __future__ import annotations

from typing import Any

from memworthy.models import Decision, Memory
from memworthy.policy.expr import BoolOp, Compare, Lit, Name, Node, Not
from memworthy.policy.loader import Policy
from memworthy.policy.schema import CheckSignal


def _walk(node: Node) -> list[Node]:
    if isinstance(node, Not):
        return [node, *_walk(node.operand)]
    if isinstance(node, BoolOp):
        return [node, *(n for o in node.operands for n in _walk(o))]
    if isinstance(node, Compare):
        return [node, *_walk(node.left), *_walk(node.right)]
    return [node]


def thresholds(policy: Policy) -> dict[str, list[float]]:
    """Numeric thresholds each signal is compared against in the rules (for the bars)."""
    from memworthy.policy.expr import parse

    out: dict[str, set[float]] = {}
    for r in policy.rules:
        if r.expr is None:
            continue
        for node in _walk(parse(r.expr.source)):
            if isinstance(node, Compare) and isinstance(node.left, Name) and \
                    isinstance(node.right, Lit) and isinstance(node.right.value, (int, float)) \
                    and not isinstance(node.right.value, bool):
                out.setdefault(".".join(node.left.parts), set()).add(float(node.right.value))
    return {k: sorted(v) for k, v in out.items()}


def policy_summary(policy: Policy) -> dict[str, Any]:
    """Rules, signal questions and type descriptions in plain form for the rules view."""
    rules = [{"id": r.id, "name": r.rule.name, "when": r.rule.when, "then": r.rule.then,
              "label": r.rule.label, "restore": r.rule.restore, "line": r.line}
             for r in policy.rules]
    signals = {name: (f"code check: {sig.check}" if isinstance(sig, CheckSignal) else sig.prompt)
               for name, sig in policy.spec.signals.items()}
    if policy.uses_conflict:
        signals["conflict"] = policy.spec.conflict.prompt
    return {"description": policy.spec.description.strip(), "rules": rules,
            "signals": signals, "type_help": dict(policy.spec.types)}


def rule_line(policy: Policy, rule_id: str) -> str:
    """The YAML line of the rule that fired (or a description for on_error)."""
    if rule_id == "on_error":
        return f"on_error: {policy.spec.on_error}"
    rule = next((r for r in policy.rules if r.id == rule_id), None)
    if rule is None or rule.line is None or not policy.text:
        return rule_id
    return policy.text.splitlines()[rule.line - 1].strip()


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def reason(policy: Policy, d: Decision) -> str:
    """One line: the type and the signal that decided it, e.g. "temporary · 99%"."""
    if d.rule == "on_error":
        return "judge unavailable: " + (d.error or "error")
    rule = next((r for r in policy.rules if r.id == d.rule), None)
    type_sig = d.signals.get("type")
    type_part = d.type
    if type_sig is not None and type_sig.probabilities:
        type_part = f"{d.type} · {_pct(type_sig.probabilities.get(d.type, 0.0))}"
    if rule is None or rule.expr is None:
        return f"{type_part} · no rule objected"
    for root in sorted(rule.expr.roots, key=lambda r: (r == "type", r == "conflict", r)):
        if root == "type":
            return type_part
        if root == "conflict":
            c = d.signals.get("conflict")
            p = (c.probabilities or {}).get(str(c.value), 0.0) if c else 0.0
            return f"changes an existing memory · {_pct(p)}"
        sig = d.signals.get(root)
        if sig is None:
            continue
        if sig.kind == "check":
            return f"{root}: {sig.value}"
        if isinstance(sig.value, float) and sig.kind == "noul":
            return f"{root} {_pct(sig.value)}"
        if isinstance(sig.value, float):
            return f"{root} {sig.value:.2f}"
        return f"{root}: {sig.value}"
    return type_part


def decision_view(policy: Policy, d: Decision, label: str) -> dict[str, Any]:
    """Everything a decision card shows."""
    signals = [s.model_dump(mode="json") for s in d.signals.values() if s is not None]
    return {
        "id": d.id, "text": d.candidate.text, "action": d.action, "type": d.type,
        "rule": d.rule, "rule_line": rule_line(policy, d.rule), "reason": reason(policy, d),
        "labels": d.labels, "error": d.error, "warnings": d.warnings, "mode": label,
        "model": d.model, "policy": d.policy, "policy_version": d.policy_version,
        "latency_ms": d.latency_ms, "redacted_text": d.redacted_text, "signals": signals,
        "target": d.target.text if d.target else None,
        "patch": d.patch.model_dump() if d.patch else None,
    }


def memory_view(m: Memory) -> dict[str, Any]:
    """A memory for the memory panel."""
    return {"id": m.id, "text": m.text, "type": m.type, "labels": m.labels,
            "previous_text": m.metadata.get("previous_text"),
            "superseded_by": m.metadata.get("superseded_by"),
            "confidence": m.metadata.get("confidence"),
            "files": m.metadata.get("files") or m.metadata.get("referenced_files") or [],
            "source": m.sources[0].text if m.sources else ""}
