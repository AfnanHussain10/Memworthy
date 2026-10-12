"""OpenAI Decisions API judge (``POST /v1/decisions``).

Contract taken from https://developers.openai.com/api/docs/guides/decisions (public beta;
see the tech spec's judge providers section).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from memworthy.judges._http import post_json
from memworthy.judges.base import Answer, JudgeError, JudgeResult, Question, validate_answers

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-luna"
QUESTION_TYPES = {"noul": "predicate", "choice": "choice", "score": "score"}


def build_request(model: str, state: str, questions: list[Question]) -> dict[str, Any]:
    """Build the Decisions request body."""
    qs: list[dict[str, Any]] = []
    for q in questions:
        body: dict[str, Any] = {"type": QUESTION_TYPES[q.kind], "name": q.name,
                                "instructions": q.prompt}
        if q.kind == "choice":
            body["choices"] = [{"value": k, "description": v}
                               for k, v in (q.options or {}).items()]
        elif q.kind == "score":
            body["levels"] = [{"label": level, "description": level}
                              for level in q.levels or []]
        qs.append(body)
    return {"model": model, "input": state, "questions": qs}


def parse_response(questions: list[Question], data: dict[str, Any]) -> dict[str, Answer]:
    """Map a Decisions response to Memworthy answers, validating every one."""
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list):
        raise JudgeError("response has no 'answers' list")
    by_name = {a.get("name"): a for a in raw_answers if isinstance(a, dict)}
    out: dict[str, Answer] = {}
    for q in questions:
        raw = by_name.get(q.name)
        if raw is None:
            raise JudgeError(f"missing answer for '{q.name}'")
        if raw.get("type") == "refusal":
            raise JudgeError(f"judge refused to answer '{q.name}'")
        try:
            out[q.name] = _parse_one(q, raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise JudgeError(f"malformed answer for '{q.name}': {exc}") from None
    validate_answers(questions, out)
    return out


def _parse_one(q: Question, raw: dict[str, Any]) -> Answer:
    if raw.get("type") != QUESTION_TYPES[q.kind]:
        raise ValueError(f"expected a {QUESTION_TYPES[q.kind]} answer, got {raw.get('type')!r}")
    if q.kind == "noul":
        return Answer(name=q.name, value=float(raw["probability"]))
    conf = raw.get("confidence")
    confidence = float(conf) if conf is not None else None
    entries = raw.get("probabilities") or []
    if q.kind == "choice":
        probs = {str(e["value"]): float(e["probability"]) for e in entries}
        return Answer(name=q.name, value=str(raw["choice"]), probabilities=probs or None,
                      confidence=confidence)
    levels = q.levels or []
    probs = {}
    for e in entries:
        index = e.get("value")
        if isinstance(index, int) and 0 <= index < len(levels):
            key = levels[index]
        elif e.get("label") in levels:
            key = str(e["label"])
        else:
            raise ValueError(f"unknown score level {index!r}")
        probs[key] = float(e["probability"])
    return Answer(name=q.name, value=float(raw["score"]), probabilities=probs or None,
                  confidence=confidence)


class OpenAIDecisionsJudge:
    """Judge backed by OpenAI's Decisions API. One POST per candidate."""

    name = "openai"

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
        """Configure from arguments, falling back to OPENAI_* env vars."""
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        if not self.api_key:
            raise JudgeError("OPENAI_API_KEY is not set; pass api_key or use MockJudge")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL)
        self.base_url = self.base_url.rstrip("/")
        self.model = model or os.environ.get("OPENAI_DECISIONS_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._client = client

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Send one Decisions request and map the answers."""
        data, latency = await self.raw(state, questions)
        answers = parse_response(questions, data)
        return JudgeResult(answers=answers, model=str(data.get("model") or self.model),
                           latency_ms=latency)

    async def raw(self, state: str, questions: list[Question]) -> tuple[dict[str, Any], int]:
        """Send the request with retries; return the raw JSON body and latency in ms."""
        return await post_json(f"{self.base_url}/decisions",
                               build_request(self.model, state, questions),
                               {"Authorization": f"Bearer {self.api_key}"}, label="OpenAI",
                               timeout=self.timeout, retries=self.retries,
                               backoff=self.backoff, client=self._client)

    def parse_raw(self, questions: list[Question], data: dict[str, Any]) -> dict[str, Answer]:
        """Map a raw Decisions response (as returned by :meth:`raw`) to answers."""
        return parse_response(questions, data)
