"""TypeSafe Jev judge over the System One HTTP API.

Contract verified against https://docs.typesafe.ai/api (see the tech spec's Jev section).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from memworthy.judges._http import post_json
from memworthy.judges.base import Answer, JudgeError, JudgeResult, Question, validate_answers

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-1.13.0"


def build_request(model: str, state: str, questions: list[Question]) -> dict[str, Any]:
    """Build the System One request body."""
    qs: dict[str, Any] = {}
    for q in questions:
        body: dict[str, Any] = {"type": q.kind, "instructions": q.prompt}
        if q.kind == "choice":
            body["criteria"] = dict(q.options or {})
        elif q.kind == "score":
            body["criteria"] = list(q.levels or [])
        qs[q.name] = body
    return {"model": model, "state": state, "questions": qs}


def parse_response(questions: list[Question], data: dict[str, Any]) -> dict[str, Answer]:
    """Map a System One response to Memworthy answers, validating every one."""
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, dict):
        raise JudgeError("response has no 'answers' object")
    out: dict[str, Answer] = {}
    for q in questions:
        raw = raw_answers.get(q.name)
        if not isinstance(raw, dict):
            raise JudgeError(f"missing answer for '{q.name}'")
        try:
            out[q.name] = _parse_one(q, raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeError(f"malformed answer for '{q.name}': {exc}") from None
    validate_answers(questions, out)
    return out


def _parse_one(q: Question, raw: dict[str, Any]) -> Answer:
    conf = raw.get("confidence")
    confidence = float(conf) if conf is not None else None
    if q.kind == "noul":
        return Answer(name=q.name, value=float(raw["noul"]))
    if q.kind == "choice":
        probs = {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()}
        return Answer(name=q.name, value=str(raw["choice"]), probabilities=probs or None,
                      confidence=confidence)
    levels = q.levels or []
    probs = {}
    for k, v in (raw.get("probabilities") or {}).items():
        key = str(k)
        if key.isdigit() and int(key) < len(levels):
            key = levels[int(key)]
        elif key not in levels:
            raise ValueError(f"unknown score level {k!r}")
        probs[key] = float(v)
    return Answer(name=q.name, value=float(raw["score"]), probabilities=probs or None,
                  confidence=confidence)


class JevJudge:
    """Judge backed by TypeSafe's Jev model. One POST per candidate."""

    name = "jev"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure from arguments, falling back to TYPESAFE_* and MEMWORTHY_MODEL env vars."""
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY") or ""
        if not self.api_key:
            raise JudgeError("TYPESAFE_API_KEY is not set; pass api_key or use MockJudge")
        self.base_url = (base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL)
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.environ.get("MEMWORTHY_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._client = client

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Send one System One request and map the answers."""
        data, latency = await self.raw(state, questions)
        answers = parse_response(questions, data)
        return JudgeResult(answers=answers, model=str(data.get("model") or self.model),
                           latency_ms=latency)

    async def raw(self, state: str, questions: list[Question]) -> tuple[dict[str, Any], int]:
        """Send the request with retries; return the raw JSON body and latency in ms."""
        return await post_json(f"{self.base_url}/systemone",
                               build_request(self.model, state, questions),
                               {"Authorization": f"Bearer {self.api_key}"}, label="Jev",
                               timeout=self.timeout, retries=self.retries,
                               backoff=self.backoff, client=self._client)

    def parse_raw(self, questions: list[Question], data: dict[str, Any]) -> dict[str, Answer]:
        """Map a raw System One response (as returned by :meth:`raw`) to answers."""
        return parse_response(questions, data)
