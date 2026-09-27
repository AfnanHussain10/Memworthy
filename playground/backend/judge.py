"""Hybrid judge for the playground: recorded answers first, live Jev only when allowed."""

from __future__ import annotations

from typing import Any

from memworthy.judges.base import Answer, JudgeError, JudgeResult, Question
from memworthy.judges.jev import parse_response
from memworthy.judges.recorded import fixture_key

from .limits import LiveLimits

MODEL = "jev-1.13.0"


class HybridJudge:
    """Answers from bundled fixtures, then client-held live answers, then live Jev.

    ``sources`` maps each state to "recorded" or "live" so every decision can be labeled.
    New live answers are returned to the client in ``new_entries``; the server keeps none.
    """

    name = "playground"

    def __init__(self, bundled: dict[str, dict[str, Any]], client_entries: dict[str, Any],
                 live: Any | None, limits: LiveLimits, ip: str) -> None:
        self.bundled = bundled
        self.client_entries = client_entries
        self.live = live
        self.limits = limits
        self.ip = ip
        self.sources: dict[str, str] = {}
        self.new_entries: dict[str, dict[str, Any]] = {}
        self.blocked: str | None = None

    def _from(self, entry: dict[str, Any], state: str, source: str) -> JudgeResult:
        self.sources[state] = source
        answers = {k: Answer.model_validate(v) for k, v in entry["answers"].items()}
        return JudgeResult(answers=answers, model=entry.get("model", MODEL),
                           latency_ms=int(entry.get("latency_ms", 0)))

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Recorded, then client-cached live, then a new live call (if allowed)."""
        key = fixture_key(state, questions, MODEL)
        if key in self.bundled:
            return self._from(self.bundled[key], state, "recorded")
        if key in self.client_entries:
            return self._from(self.client_entries[key], state, "live")
        if self.live is None:
            self.sources[state] = "needs-live"
            raise JudgeError("not recorded; live mode is off")
        reason = self.limits.check(self.ip)
        if reason:
            self.blocked = reason
            self.sources[state] = "needs-live"
            raise JudgeError(reason)
        raw, latency = await self.live.raw(state, questions)
        answers = parse_response(questions, raw)
        tokens = int((raw.get("usage") or {}).get("input_tokens", 0))
        self.limits.record(self.ip, tokens)
        entry = {"answers": {k: a.model_dump(mode="json") for k, a in answers.items()},
                 "model": raw.get("model", MODEL), "latency_ms": latency}
        self.new_entries[key] = entry
        self.sources[state] = "live"
        return JudgeResult(answers=answers, model=entry["model"], latency_ms=latency)
