"""A few real OpenAI Decisions calls. Skipped unless OPENAI_API_KEY is set; never in PR CI."""

from __future__ import annotations

import pytest

from memworthy.judges.base import Question
from memworthy.judges.openai_decisions import OpenAIDecisionsJudge

pytestmark = pytest.mark.live


async def test_live_decisions_answers_all_kinds() -> None:
    judge = OpenAIDecisionsJudge()
    qs = [Question(name="kind", kind="choice", prompt="What kind of information is this?",
                   options={"fact": "A durable fact", "temporary": "A short-lived state"}),
          Question(name="durable", kind="noul", prompt="Will this still be true in a year?"),
          Question(name="sens", kind="score", prompt="How sensitive is this?",
                   levels=["Low", "Medium", "High"])]
    data, _ = await judge.raw("New message: I live in Dubai\nAbout: user", qs)
    result = judge.parse_raw(qs, data)
    assert result["kind"].value == "fact"
    assert 0.0 <= float(result["durable"].value) <= 1.0
    assert set(result["sens"].probabilities or {}) <= {"Low", "Medium", "High"}
