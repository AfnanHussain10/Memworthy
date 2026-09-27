"""Re-decide ledger decisions under a new policy and report which would change."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from memworthy.checks.registry import get_check
from memworthy.engine import (
    CONFLICT_NONE,
    RuleContext,
    build_questions,
    finish_decision,
    mask,
    questions_hash,
    render_state,
    run_rules,
    to_signal,
)
from memworthy.judges.base import Judge, JudgeError, validate_answers
from memworthy.models import Decision, SignalValue
from memworthy.policy.loader import Policy

Method = Literal["rules", "rejudged", "needs_live"]


@dataclass
class ReplayResult:
    """One ledger decision re-evaluated under a new policy."""

    old: Decision
    new: Decision | None
    method: Method
    reason: str = ""

    @property
    def changed(self) -> bool:
        """True when the new action or labels differ (unknown results count as unchanged)."""
        if self.new is None:
            return False
        return (self.new.action, sorted(self.new.labels)) != \
            (self.old.action, sorted(self.old.labels))


def _checks(policy: Policy, old: Decision) -> dict[str, SignalValue | None]:
    """Reuse recorded check values by name; compute checks the old policy lacked."""
    out: dict[str, SignalValue | None] = {}
    for name, chk in policy.check_signals.items():
        prev = old.signals.get(name)
        if prev is not None and prev.kind == "check":
            out[name] = prev
            continue
        fn = get_check(chk.check)
        assert fn is not None
        out[name] = SignalValue(name=name, kind="check", value=fn(old.candidate, dict(chk.args)))
    return out


def _context(policy: Policy, old: Decision) -> RuleContext:
    signals = _checks(policy, old)
    for name in policy.model_signals:
        signals[name] = old.signals.get(name)
    signals["type"] = old.signals.get("type")
    signals["conflict"] = old.signals.get("conflict")
    ctx = RuleContext(candidate=old.candidate, signals=signals,
                      type=None if old.type == "unknown" else old.type,
                      conflict=old.signals.get("conflict"), target=old.target)
    return ctx


def _finish(policy: Policy, old: Decision, ctx: RuleContext) -> Decision | None:
    matched = run_rules(policy, ctx)
    if matched is None:  # pragma: no cover  (the final else always matches)
        return None
    return finish_decision(policy, ctx, matched[0], matched[1], judge=old.judge,
                           model=old.model, redacted_text=old.redacted_text,
                           latency_ms=0)


def replay_rules(policy: Policy, old: Decision) -> ReplayResult:
    """Re-run rules over recorded signals, or explain why a judge call is needed."""
    ctx = _context(policy, old)
    early = run_rules(policy, ctx, only_pre=True)
    if early is not None and early[1] in ("reject", "review"):
        new = finish_decision(policy, ctx, early[0], early[1], judge=old.judge, model=None,
                              redacted_text=old.redacted_text, latency_ms=0)
        return ReplayResult(old, new, "rules")
    if old.error or old.type == "unknown":
        return ReplayResult(old, None, "needs_live", "no judge answers recorded for this "
                            "decision")
    if old.questions_hash != questions_hash(policy):
        return ReplayResult(old, None, "needs_live", "policy questions changed")
    missing = [n for n, s in policy.model_signals.items()
               if ctx.signals.get(n) is None and (s.applies_to is None
                                                   or old.type in s.applies_to)]
    if missing:
        return ReplayResult(old, None, "needs_live",
                            f"no recorded value for {', '.join(missing)}")
    mask(policy, ctx.signals, ctx.type)
    return ReplayResult(old, _finish(policy, old, ctx), "rules")


async def rejudge(policy: Policy, old: Decision, judge: Judge) -> ReplayResult:
    """Re-ask the judge (usually a RecordedJudge) with the new policy's questions."""
    shortlist = [old.target] if old.target is not None else []
    questions = build_questions(policy, shortlist)
    try:
        result = await judge.judge(render_state(old.candidate), questions)
        validate_answers(questions, result.answers)
    except JudgeError as exc:
        return ReplayResult(old, None, "needs_live", str(exc))
    ctx = _context(policy, old)
    for q in questions:
        sig = to_signal(q.name, q.kind, result.answers[q.name])
        ctx.signals[q.name] = sig
        if q.name == "type":
            ctx.type = str(sig.value)
        if q.name == "conflict":
            ctx.conflict = sig
            ctx.target = old.target if sig.value != CONFLICT_NONE else None
    mask(policy, ctx.signals, ctx.type)
    return ReplayResult(old, _finish(policy, old, ctx), "rejudged")


async def replay(policy: Policy, decisions: Iterable[Decision],
                 judge: Judge | None = None) -> list[ReplayResult]:
    """Replay every decision: rules where possible, then the judge (if given)."""
    out = []
    for old in decisions:
        res = replay_rules(policy, old)
        if res.method == "needs_live" and judge is not None and not old.error:
            res = await rejudge(policy, old, judge)
        out.append(res)
    return out
