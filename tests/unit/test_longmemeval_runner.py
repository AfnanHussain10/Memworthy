"""Offline test of eval/longmemeval.py with a fake LLM and a mock judge."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from memgate import MockJudge

PATH = Path(__file__).resolve().parents[2] / "eval" / "longmemeval.py"
spec = importlib.util.spec_from_file_location("lme", PATH)
assert spec and spec.loader
lme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lme)

QUESTION = {
    "question_id": "q1", "question_type": "knowledge-update",
    "question": "What is my 5K personal best?", "answer": "25:50",
    "question_date": "2023/06/25 (Sun) 13:22",
    "haystack_dates": ["2023/05/01 (Mon) 10:00", "2023/06/01 (Thu) 10:00"],
    "haystack_sessions": [
        [{"role": "user", "content": "My 5K personal best is 27:12."},
         {"role": "assistant", "content": "Nice!"}],
        [{"role": "user", "content": "New 5K personal best: 25:50!"}],
    ],
}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        system = messages[0]["content"]
        self.calls.append(system[:10])
        if system.startswith("Extract"):
            return json.dumps({"entries": [
                {"date": "2023/05/01 (Mon) 10:00", "text": "My 5K personal best is 27:12"},
                {"date": "2023/06/01 (Thu) 10:00", "text": "My 5K personal best is 25:50"}]})
        if system.startswith("Answer"):
            body = messages[1]["content"]
            return "25:50" if "25:50" in body else "27:12"
        return '{"a": false, "b": true}'


async def test_pipeline_pieces(tmp_path: Path) -> None:
    client = FakeClient()
    llm = lme.LLM(client, "m", max_calls=10, cache=tmp_path / "cache")
    facts = await lme.extract(llm, QUESTION)
    assert [t for _, t in facts] == ["My 5K personal best is 27:12",
                                     "My 5K personal best is 25:50"]
    again = await lme.extract(llm, QUESTION)  # served from the cache
    assert again == facts and client.calls.count("Extract ev") == 1
    judge = MockJudge(defaults={"type": "fact", "durable": 0.9, "explicit": 0.9,
                                "about_subject": 0.9, "sensitivity": 0.1, "retraction": 0.0,
                                "conflict": {"m0": 0.9, "none": 0.1}})
    gated, counts = await lme.gate_facts(facts, judge)
    assert counts == {"store": 1, "update": 1}
    assert [m.text for m in gated.memories.values()] == ["My 5K personal best is 25:50"]
    base = lme.baseline_store(facts)
    assert len(base.memories) == 2
    top = lme.top_memories(base, QUESTION["question"])
    assert top[0].startswith("(2023/05/01") and len(top) == 2
    a = await lme.answer(llm, "baseline", QUESTION, top)
    b = await lme.answer(llm, "memgate", QUESTION, lme.top_memories(gated, "5K personal best"))
    assert await lme.grade(llm, QUESTION, a, b) == (False, True)
    assert lme._iso("2023/05/20 (Sat) 02:21") == "2023-05-20T12:00:00+00:00"
    assert lme._iso("bad") == ""


async def test_budget_stops(tmp_path: Path) -> None:
    llm = lme.LLM(FakeClient(), "m", max_calls=0, cache=tmp_path)
    with pytest.raises(lme.Budget):
        await llm.ask("k", [{"role": "system", "content": "Extract"}])

    class Failing:
        async def complete(self, *a: Any) -> str:
            raise RuntimeError("429")

    llm2 = lme.LLM(Failing(), "m", max_calls=5, cache=tmp_path / "c2")
    with pytest.raises(lme.Budget, match="429"):
        await llm2.ask("k", [])
