"""Evaluation algorithm: checks, one judge call, rules, apply, ledger."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from memgate.checks import builtins as _builtins  # noqa: F401  (registers built-in checks)
from memgate.checks.registry import get_check, get_rule
from memgate.checks.secrets import redact_candidate
from memgate.judges.base import (
    Answer,
    Judge,
    JudgeError,
    JudgeResult,
    Question,
    validate_answers,
)
from memgate.ledger import Ledger
from memgate.models import Action, Candidate, Decision, Memory, Patch, SignalValue
from memgate.policy.expr import truthy
from memgate.policy.loader import CompiledRule, Policy
from memgate.stores.base import WRITE_ACTIONS, MemoryStore

log = logging.getLogger("memgate.engine")
CONFLICT_NONE = "none"
NEEDS_TARGET = frozenset({"update", "merge", "supersede"})
METADATA_LINES = {
    "episode_type": "Episode type",
    "outcome": "Episode outcome",
    "files_read": "Files read in session",
    "files_edited": "Files edited in session",
    "referenced_files": "Files referenced",
    "commands": "Commands run",
    "dependency_versions": "Dependency versions",
}


@dataclass
class RuleContext:
    """Everything a rule can see; also the argument passed to ``py:`` rules."""

    candidate: Candidate
    signals: dict[str, SignalValue | None]
    type: str | None
    conflict: SignalValue | None = None
    target: Memory | None = None
    warnings: list[str] = field(default_factory=list)

    def lookup(self, parts: tuple[str, ...]) -> Any:
        """Resolve a dotted expression name to a value (None when not evaluated)."""
        root, rest = parts[0], parts[1:]
        if root == "type":
            return self.type
        if root == "conflict":
            picked = self.conflict is not None and self.conflict.value != CONFLICT_NONE
            if not rest:
                return picked
            if not picked or self.conflict is None:
                return None
            return (self.conflict.probabilities or {}).get(str(self.conflict.value))
        if root == "candidate":
            return getattr(self.candidate, rest[0], None) if rest else None
        if root == "meta":
            value: Any = self.candidate.metadata
            for p in rest:
                value = value.get(p) if isinstance(value, dict) else None
            return value
        sig = self.signals.get(root)
        if sig is None:
            return None
        if not rest:
            return sig.value
        probs = sig.probabilities or {}
        if rest == ("p",):
            key = str(sig.value) if sig.kind == "choice" else _top(probs)
            return probs.get(key) if key is not None else None
        if rest == ("top",):
            return _top(probs)
        return probs.get(rest[0], 0.0)

    def warn(self, message: str) -> None:
        """Record an evaluation warning on the decision."""
        if message not in self.warnings:
            self.warnings.append(message)


def _top(probs: dict[str, float]) -> str | None:
    return max(probs, key=lambda k: probs[k]) if probs else None


def render_state(c: Candidate) -> str:
    """Plain-text state sent to the judge, in a fixed order with empty fields omitted.

    Earlier conversation comes first as its own block; the candidate is labeled
    ``New message`` when it is the message itself, else ``Candidate memory`` followed by
    the original message. (Measured on Jev: context placed after the candidate made
    durable facts look short-lived.)
    """
    lines: list[str] = []
    if c.context:
        lines += ["Earlier messages:", c.context, ""]
    is_message = not c.source.text or c.source.text.strip() == c.text.strip()
    lines.append(f"New message: {c.text}" if is_message else f"Candidate memory: {c.text}")
    lines += [f"About: {c.subject}", f"Source: {c.source.role} message"]
    if not is_message:
        lines.append(f"Original message: {c.source.text}")
    for key, label in METADATA_LINES.items():
        value = c.metadata.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            value = ", ".join(f"{k} {v}" for k, v in value.items())
        elif isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value[:30])
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def build_questions(policy: Policy, shortlist: list[Memory]) -> list[Question]:
    """The type question, every model signal, and the conflict question if needed."""
    qs: list[Question] = []
    if len(policy.spec.types) > 1:
        qs.append(Question(name="type", kind="choice",
                           prompt="What kind of information is this?",
                           options=dict(policy.spec.types)))
    for name, sig in policy.model_signals.items():
        qs.append(Question(name=name, kind=sig.kind, prompt=sig.prompt,
                           options=sig.options, levels=sig.levels))
    if shortlist:
        opts = {f"m{i}": m.text for i, m in enumerate(shortlist)}
        opts[CONFLICT_NONE] = "No existing memory is updated or contradicted"
        qs.append(Question(name="conflict", kind="choice",
                           prompt=policy.spec.conflict.prompt, options=opts))
    return qs


def to_signal(name: str, kind: str, answer: Answer) -> SignalValue:
    """Convert a judge answer into a SignalValue."""
    return SignalValue(name=name, kind=kind, value=answer.value,
                       probabilities=answer.probabilities, confidence=answer.confidence)


def run_rules(policy: Policy, ctx: RuleContext, only_pre: bool = False
              ) -> tuple[CompiledRule, Action] | None:
    """First matching rule and its action. With ``only_pre``, stop at the first rule that
    needs model signals."""
    for r in policy.rules:
        if only_pre and not r.pre_judge:
            return None
        if r.py is not None:
            fn = get_rule(r.py)
            action = fn(ctx) if fn is not None else None
            if action is not None:
                return r, action
            continue
        if r.expr is None or r.expr.evaluate(ctx):
            return r, r.rule.then
    return None  # pragma: no cover  (the final else always matches)


def mask(policy: Policy, signals: dict[str, SignalValue | None], type_: str | None) -> None:
    """Null out model signals whose ``applies_to`` excludes the chosen type."""
    for name, sig in policy.model_signals.items():
        if sig.applies_to is not None and type_ not in sig.applies_to:
            signals[name] = None


def finish_decision(policy: Policy, ctx: RuleContext, rule: CompiledRule, action: Action,
                    **fields: Any) -> Decision:
    """Build the Decision for a matched rule, including labels, target and patch."""
    target = ctx.target
    warnings = list(ctx.warnings)
    if action in NEEDS_TARGET and target is None:
        warnings.append(f"rule '{rule.id}' chose {action} without a conflicting memory; stored")
        action = "store"
    labels: list[str] = []
    if action == "store_labeled" and rule.rule.label:
        labels.append(rule.rule.label)
    if fields.get("redacted_text"):
        labels.append("redacted")
    patch: Patch | None = None
    text = fields.get("redacted_text") or ctx.candidate.text
    if target is not None and action in ("update", "supersede"):
        if action == "supersede" and rule.rule.restore:
            prev = target.metadata.get("previous_text")
            patch = Patch(target_id=target.id, old_text=target.text, new_text=str(prev),
                          restore=True) if prev else None
        else:
            patch = Patch(target_id=target.id, old_text=target.text, new_text=text)
    return Decision(
        candidate=ctx.candidate, action=action, type=ctx.type or "unknown",
        signals=ctx.signals, rule=rule.id, labels=labels,
        target=target if action in NEEDS_TARGET else None, patch=patch,
        policy=policy.name, policy_version=policy.version, warnings=warnings, **fields)


class Engine:
    """Runs the per-candidate algorithm for one policy, store, judge and ledger."""

    def __init__(self, policy: Policy, store: MemoryStore, judge: Judge,
                 ledger: Ledger | None, apply: bool = True) -> None:
        """Bind the engine's collaborators."""
        self.policy = policy
        self.store = store
        self.judge = judge
        self.ledger = ledger
        self.apply = apply

    async def decide(self, candidate: Candidate) -> Decision:
        """Gate one candidate end to end."""
        start = time.perf_counter()
        decision = await self._decide(candidate, start)
        if self.apply and decision.action in WRITE_ACTIONS and decision.error is None:
            try:
                await self.store.apply(decision)
            except Exception as exc:
                failed = decision.model_copy(update={"error": f"store apply failed: {exc}"})
                self._record(failed)
                raise
        self._record(decision)
        return decision

    def _record(self, decision: Decision) -> None:
        if self.ledger is None:
            return
        try:
            self.ledger.record(decision)
        except Exception as exc:
            log.warning("ledger write failed: %s", exc)

    async def _decide(self, candidate: Candidate, start: float) -> Decision:
        policy = self.policy
        signals: dict[str, SignalValue | None] = {}
        redacted: str | None = None
        for name, chk in policy.check_signals.items():
            fn = get_check(chk.check)
            assert fn is not None  # validated at load
            value = fn(candidate, dict(chk.args))
            if chk.check == "secret_scan" and value is True:
                candidate, redacted = redact_candidate(candidate, dict(chk.args))
            signals[name] = SignalValue(name=name, kind="check", value=value)
        for name in policy.model_signals:
            signals[name] = None
        signals["type"] = None
        signals["conflict"] = None
        single_type = next(iter(policy.spec.types)) if len(policy.spec.types) == 1 else None
        ctx = RuleContext(candidate=candidate, signals=signals, type=single_type)
        extra: dict[str, Any] = {"redacted_text": redacted, "judge": self.judge.name}

        early = run_rules(policy, ctx, only_pre=True)
        if early is not None and early[1] in ("reject", "review"):
            return finish_decision(policy, ctx, early[0], early[1], model=None,
                                   latency_ms=_ms(start), **extra)

        shortlist: list[Memory] = []
        if policy.uses_conflict:
            shortlist = await self.store.similar(candidate, policy.spec.conflict.k)
        questions = build_questions(policy, shortlist)
        try:
            result: JudgeResult = await self.judge.judge(render_state(candidate), questions)
            validate_answers(questions, result.answers)
        except JudgeError as exc:
            return self._on_error(ctx, str(exc), start, extra)
        except Exception as exc:  # judges must never crash the pipeline
            return self._on_error(ctx, f"{type(exc).__name__}: {exc}", start, extra)

        answers = result.answers
        for q in questions:
            if q.name in ("type", "conflict"):
                continue
            signals[q.name] = to_signal(q.name, q.kind, answers[q.name])
        if single_type is None:
            signals["type"] = to_signal("type", "choice", answers["type"])
            ctx.type = str(answers["type"].value)
        else:
            signals["type"] = SignalValue(name="type", kind="choice", value=single_type,
                                          probabilities={single_type: 1.0}, confidence=1.0)
        if shortlist:
            conf = to_signal("conflict", "choice", answers["conflict"])
            signals["conflict"] = conf
            ctx.conflict = conf
            if conf.value != CONFLICT_NONE:
                ctx.target = shortlist[int(str(conf.value)[1:])]
        mask(policy, signals, ctx.type)
        matched = run_rules(policy, ctx)
        assert matched is not None
        return finish_decision(policy, ctx, matched[0], matched[1], model=result.model,
                               latency_ms=_ms(start), **extra)

    def _on_error(self, ctx: RuleContext, error: str, start: float,
                  extra: dict[str, Any]) -> Decision:
        log.warning("judge error, applying on_error=%s: %s", self.policy.spec.on_error, error)
        return Decision(
            candidate=ctx.candidate, action=self.policy.spec.on_error,
            type=ctx.type or "unknown", signals=ctx.signals, rule="on_error",
            labels=["redacted"] if extra.get("redacted_text") else [],
            policy=self.policy.name, policy_version=self.policy.version, error=error,
            model=None, latency_ms=_ms(start), **extra)


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


__all__ = ["Engine", "RuleContext", "build_questions", "render_state", "run_rules", "truthy"]
