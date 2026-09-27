"""A handful of real Jev calls. Skipped unless TYPESAFE_API_KEY is set; never in PR CI."""

from __future__ import annotations

import pytest

from memworthy import Candidate, DictStore, Gate, MemoryLedger
from memworthy.judges.base import Question
from memworthy.judges.jev import JevJudge

pytestmark = pytest.mark.live


async def test_live_system_one_answers_all_kinds() -> None:
    judge = JevJudge()
    qs = [Question(name="kind", kind="choice", prompt="What kind of information is this?",
                   options={"fact": "A durable fact", "temporary": "A short-lived state"}),
          Question(name="durable", kind="noul", prompt="Will this still be true in a year?"),
          Question(name="sens", kind="score", prompt="How sensitive is this?",
                   levels=["Low", "Medium", "High"])]
    result = await judge.judge("New message: I live in Dubai\nAbout: user", qs)
    assert result.model == "jev-1.13.0"
    assert result.answers["kind"].value == "fact"
    assert set(result.answers["sens"].probabilities or {}) == {"Low", "Medium", "High"}


def test_live_gate_personal_memory() -> None:
    gate = Gate("personal-memory", DictStore(), ledger=MemoryLedger())
    [stored, temp] = gate.evaluate([Candidate.from_text("I live in Lisbon"),
                                    Candidate.from_text("I'm at the airport right now",
                                                        subject="other")])
    assert stored.action == "store" and temp.action == "reject"
    assert stored.latency_ms > 0 and stored.error is None
