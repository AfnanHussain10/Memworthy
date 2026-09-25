"""Pin the System One request/response shapes against recorded real responses."""

from __future__ import annotations

import pytest

from memgate.judges.base import Answer, Question
from memgate.judges.jev import build_request, parse_response
from memgate.judges.recorded import FixtureFile, bundled_fixture_path, fixture_key

pytestmark = pytest.mark.contract
POLICIES = ["personal-memory", "dev-sessions"]


def _entries(policy: str) -> list[dict]:  # type: ignore[type-arg]
    path = bundled_fixture_path(policy)
    if path is None:
        pytest.skip(f"no bundled fixtures for {policy}")
    fx = FixtureFile(path)
    assert not fx.synthetic
    return list(fx.entries.items())  # type: ignore[return-value]


@pytest.mark.parametrize("policy", POLICIES)
def test_recorded_raw_responses_parse_to_stored_answers(policy: str) -> None:
    entries = _entries(policy)
    assert entries
    for key, entry in entries:
        questions = [Question.model_validate(q) for q in entry["questions"]]
        assert fixture_key(entry["state"], questions, "jev-1.13.0") == key
        raw = entry["raw"]
        assert raw is not None, "fixtures must keep the raw Jev response"
        assert raw["model"] == "jev-1.13.0"
        assert set(raw["answers"]) == {q.name for q in questions}
        for q in questions:
            ans = raw["answers"][q.name]
            assert ans["type"] == q.kind
            if q.kind == "noul":
                assert set(ans) == {"type", "noul"}
            elif q.kind == "choice":
                assert {"choice", "confidence", "probabilities"} <= set(ans)
                assert set(ans["probabilities"]) <= set(q.options or {})
            else:
                assert {"score", "confidence", "probabilities", "legend"} <= set(ans)
                assert all(k.isdigit() for k in ans["probabilities"])
        parsed = parse_response(questions, raw)
        stored = {k: Answer.model_validate(v) for k, v in entry["answers"].items()}
        assert parsed == stored
        body = build_request("jev-1.13.0", entry["state"], questions)
        assert set(body) == {"model", "state", "questions"}
