"""Pin Microsoft-Decision-1's System One responses against recorded real responses."""

from __future__ import annotations

import json
from typing import Any

import pytest

from memworthy.judges.base import Question
from memworthy.judges.systemone import build_request, parse_response
from tests.conftest import FIXTURES

pytestmark = pytest.mark.contract
DATA = json.loads((FIXTURES / "foundry" / "systemone_responses.json").read_text("utf-8"))


def test_fixtures_are_real_recordings() -> None:
    assert DATA["synthetic"] is False and DATA["entries"]


@pytest.mark.parametrize("entry", DATA["entries"], ids=lambda e: e["state"].split("\n")[0])
def test_recorded_responses_match_the_shapes_we_parse(entry: dict[str, Any]) -> None:
    questions = [Question.model_validate(q) for q in entry["questions"]]
    raw = entry["raw"]
    assert set(raw) == {"model", "answers", "usage"}
    # The response names the underlying model, never the caller's deployment name.
    assert raw["model"] == "microsoft-decision-1"
    assert set(raw["answers"]) == {q.name for q in questions}
    for q in questions:
        ans = raw["answers"][q.name]
        assert ans["type"] == q.kind
        if q.kind == "noul":
            assert set(ans) == {"type", "noul"}
        elif q.kind == "choice":
            assert set(ans) == {"type", "choice", "confidence", "probabilities"}
            assert set(ans["probabilities"]) == set(q.options or {})
        else:
            assert set(ans) == {"type", "score", "confidence", "probabilities", "legend"}
            assert ans["legend"] == {str(i): lv for i, lv in enumerate(q.levels or [])}
            assert all(k.isdigit() for k in ans["probabilities"])
    parsed = parse_response(questions, raw)
    assert set(parsed) == {q.name for q in questions}
    body = build_request("Decision-1", entry["state"], questions)
    assert set(body) == {"model", "state", "questions"}
