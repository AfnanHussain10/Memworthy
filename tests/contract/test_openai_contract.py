"""Pin the OpenAI Decisions request/response shapes against recorded real responses."""

from __future__ import annotations

import json
from typing import Any

import pytest

from memworthy.judges.base import JudgeError, Question
from memworthy.judges.openai_decisions import QUESTION_TYPES, build_request, parse_response
from tests.conftest import FIXTURES

pytestmark = pytest.mark.contract
DATA = json.loads((FIXTURES / "openai" / "decisions_responses.json").read_text("utf-8"))


def test_fixtures_are_real_recordings() -> None:
    assert DATA["synthetic"] is False and DATA["entries"] and DATA["refusal"]["raw"]


@pytest.mark.parametrize("entry", DATA["entries"], ids=lambda e: e["state"].split("\n")[0])
def test_recorded_responses_match_the_shapes_we_parse(entry: dict[str, Any]) -> None:
    questions = [Question.model_validate(q) for q in entry["questions"]]
    raw = entry["raw"]
    assert set(raw) == {"model", "answers", "usage"}
    assert raw["model"] == "gpt-6-luna" and raw["usage"]["output_tokens"] == 0
    by_name = {a["name"]: a for a in raw["answers"]}
    assert set(by_name) == {q.name for q in questions}
    for q in questions:
        ans = by_name[q.name]
        assert ans["type"] == QUESTION_TYPES[q.kind]
        if q.kind == "noul":
            assert set(ans) == {"type", "name", "probability"}
        elif q.kind == "choice":
            assert set(ans) == {"type", "name", "choice", "probabilities", "confidence"}
            assert [p["value"] for p in ans["probabilities"]] == list(q.options or {})
        else:
            assert set(ans) == {"type", "name", "score", "probabilities", "confidence"}
            assert [(p["value"], p["label"]) for p in ans["probabilities"]] == list(
                enumerate(q.levels or []))
    parsed = parse_response(questions, raw)
    assert set(parsed) == {q.name for q in questions}
    body = build_request("gpt-6-luna", entry["state"], questions)
    assert set(body) == {"model", "input", "questions"}


def test_recorded_refusal_shape_and_handling() -> None:
    entry = DATA["refusal"]
    questions = [Question.model_validate(q) for q in entry["questions"]]
    answers = {a["name"]: a for a in entry["raw"]["answers"]}
    assert answers["control"]["type"] == "predicate"
    for name in ("orientation", "ethnicity", "criminal"):
        assert answers[name] == {"type": "refusal", "name": name}
    with pytest.raises(JudgeError, match="refused to answer 'orientation'"):
        parse_response(questions, entry["raw"])
