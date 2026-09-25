"""Deterministic judge for tests and offline use."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from memgate.judges.base import Answer, JudgeError, JudgeResult, Question

AnswerSpec = Any  # float for noul; option name or {option: p} for choice; level/position for score
Responder = Callable[[str, list[Question]], Mapping[str, AnswerSpec]]


class MockJudge:
    """Returns fixed or rule-based answers and records every call.

    ``defaults`` apply to every state; ``rules`` is an ordered list of ``(pattern, answers)``
    where ``pattern`` is a regex searched in the state and later matches override earlier ones;
    ``responder`` computes answers from the state and questions. Unspecified questions get
    ``noul=default_noul``, the first choice option, or the first score level.
    """

    name = "mock"

    def __init__(
        self,
        defaults: Mapping[str, AnswerSpec] | None = None,
        rules: list[tuple[str, Mapping[str, AnswerSpec]]] | None = None,
        responder: Responder | None = None,
        default_noul: float = 0.5,
        model: str | None = "mock",
        fail: bool = False,
    ) -> None:
        """Configure the fixed answers; ``fail=True`` makes every call raise JudgeError."""
        self.defaults = dict(defaults or {})
        self.rules = [(re.compile(p), dict(a)) for p, a in (rules or [])]
        self.responder = responder
        self.default_noul = default_noul
        self.model = model
        self.fail = fail
        self.calls: list[tuple[str, list[Question]]] = []

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Answer from defaults, matching rules and the responder, in that order."""
        self.calls.append((state, list(questions)))
        if self.fail:
            raise JudgeError("mock judge configured to fail")
        spec: dict[str, AnswerSpec] = dict(self.defaults)
        for pattern, answers in self.rules:
            if pattern.search(state):
                spec.update(answers)
        if self.responder is not None:
            spec.update(self.responder(state, questions))
        answers_out = {q.name: self._answer(q, spec.get(q.name)) for q in questions}
        return JudgeResult(answers=answers_out, model=self.model, latency_ms=0)

    def _answer(self, q: Question, spec: AnswerSpec) -> Answer:
        if q.kind == "noul":
            p = self.default_noul if spec is None else float(spec)
            return Answer(name=q.name, value=p)
        if q.kind == "choice":
            return _choice(q, spec)
        return _score(q, spec)


def _choice(q: Question, spec: AnswerSpec) -> Answer:
    options = list(q.options or {})
    if isinstance(spec, Mapping):
        probs = {k: float(spec.get(k, 0.0)) for k in options}
    else:
        chosen = options[0] if spec is None else str(spec)
        if chosen not in options:
            # An unknown option is passed through so tests can exercise judge-error handling.
            return Answer(name=q.name, value=chosen, probabilities={chosen: 1.0}, confidence=1.0)
        rest = (1.0 - 0.9) / max(len(options) - 1, 1)
        probs = {k: (0.9 if k == chosen else rest) for k in options}
    best = max(probs, key=lambda k: probs[k])
    return Answer(name=q.name, value=best, probabilities=probs, confidence=probs[best])


def _score(q: Question, spec: AnswerSpec) -> Answer:
    levels = q.levels or []
    if not levels:
        raise JudgeError(f"score question '{q.name}' has no levels")
    if isinstance(spec, str):
        if spec not in levels:
            raise JudgeError(f"unknown level {spec!r} for '{q.name}'")
        idx = levels.index(spec)
        probs = {lv: (1.0 if i == idx else 0.0) for i, lv in enumerate(levels)}
        return Answer(name=q.name, value=float(idx), probabilities=probs, confidence=1.0)
    pos = 0.0 if spec is None else float(spec)
    pos = min(max(pos, 0.0), float(len(levels) - 1))
    lo = int(pos)
    hi = min(lo + 1, len(levels) - 1)
    frac = pos - lo
    probs = {lv: 0.0 for lv in levels}
    probs[levels[lo]] += 1.0 - frac
    probs[levels[hi]] += frac
    top = max(probs, key=lambda k: probs[k])
    return Answer(name=q.name, value=pos, probabilities=probs, confidence=probs[top])
