"""Judge interface: answer typed questions about a state, with probabilities."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class Question(BaseModel):
    """A judge-agnostic question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: Literal["noul", "choice", "score"]
    prompt: str
    options: dict[str, str] | None = None
    levels: list[str] | None = None


class Answer(BaseModel):
    """A judge's answer. Score probabilities are keyed by level name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    value: float | str
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


class JudgeResult(BaseModel):
    """All answers from one judge call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answers: dict[str, Answer]
    model: str | None = None
    latency_ms: int = 0


class JudgeError(Exception):
    """The judge failed, timed out, or returned unusable answers."""


@runtime_checkable
class Judge(Protocol):
    """Anything that can answer a batch of questions about one state."""

    name: str

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Answer every question about ``state`` in one call."""
        ...


def validate_answers(questions: list[Question], answers: dict[str, Answer]) -> None:
    """Raise JudgeError if any answer is missing or names an unknown option."""
    for q in questions:
        a = answers.get(q.name)
        if a is None:
            raise JudgeError(f"missing answer for '{q.name}'")
        if q.kind == "noul":
            if not isinstance(a.value, (int, float)) or not 0.0 <= float(a.value) <= 1.0:
                raise JudgeError(f"noul answer for '{q.name}' is not a probability")
        elif q.kind == "choice":
            if a.value not in (q.options or {}):
                raise JudgeError(f"unknown option {a.value!r} for '{q.name}'")
        elif not isinstance(a.value, (int, float)):
            raise JudgeError(f"score answer for '{q.name}' is not a number")
