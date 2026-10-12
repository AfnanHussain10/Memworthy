from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from memworthy.judges.base import JudgeError, Question
from memworthy.judges.openai_decisions import OpenAIDecisionsJudge, build_request, parse_response
from memworthy.judges.recorded import FixtureFile, RecordedJudge, RecordingJudge

QS = [
    Question(name="type", kind="choice", prompt="What kind?",
             options={"fact": "A fact", "temporary": "Short-lived"}),
    Question(name="durable", kind="noul", prompt="Still true in a year?"),
    Question(name="sensitivity", kind="score", prompt="How sensitive?",
             levels=["Not sensitive", "Personal", "Highly sensitive"]),
]
# Answer shapes from the examples in OpenAI's Decisions guide (values made up); answers are
# deliberately out of question order because the guide only promises a matching `name`.
RESPONSE = {
    "model": "gpt-6-luna",
    "answers": [
        {"type": "predicate", "name": "durable", "probability": 0.73},
        {"type": "score", "name": "sensitivity", "score": 0.88, "confidence": 0.82,
         "probabilities": [{"value": 0, "label": "Not sensitive", "probability": 0.12},
                           {"value": 1, "label": "Personal", "probability": 0.88},
                           {"value": 2, "label": "Highly sensitive", "probability": 0.0}]},
        {"type": "choice", "name": "type", "choice": "fact", "confidence": 0.93,
         "probabilities": [{"value": "fact", "probability": 0.96},
                           {"value": "temporary", "probability": 0.04}]},
    ],
}


def test_build_request_shape() -> None:
    assert build_request("gpt-6-luna", "state text", QS) == {
        "model": "gpt-6-luna",
        "input": "state text",
        "questions": [
            {"type": "choice", "name": "type", "instructions": "What kind?",
             "choices": [{"value": "fact", "description": "A fact"},
                         {"value": "temporary", "description": "Short-lived"}]},
            {"type": "predicate", "name": "durable", "instructions": "Still true in a year?"},
            {"type": "score", "name": "sensitivity", "instructions": "How sensitive?",
             "levels": [{"label": "Not sensitive", "description": "Not sensitive"},
                        {"label": "Personal", "description": "Personal"},
                        {"label": "Highly sensitive", "description": "Highly sensitive"}]},
        ],
    }


def test_parse_response_matches_by_name_and_maps_levels() -> None:
    answers = parse_response(QS, RESPONSE)
    assert answers["type"].value == "fact" and answers["type"].confidence == 0.93
    assert answers["type"].probabilities == {"fact": 0.96, "temporary": 0.04}
    assert answers["durable"].value == 0.73 and answers["durable"].confidence is None
    assert answers["sensitivity"].value == 0.88
    assert answers["sensitivity"].probabilities == {
        "Not sensitive": 0.12, "Personal": 0.88, "Highly sensitive": 0.0}


def test_parse_score_falls_back_to_label() -> None:
    data = json.loads(json.dumps(RESPONSE))
    for e in data["answers"][1]["probabilities"]:
        e.pop("value")
    assert parse_response(QS, data)["sensitivity"].probabilities == {
        "Not sensitive": 0.12, "Personal": 0.88, "Highly sensitive": 0.0}


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda r: r.pop("answers"), "no 'answers'"),
        (lambda r: r.update(answers={"durable": {}}), "no 'answers'"),
        (lambda r: r["answers"].pop(0), "missing answer"),
        (lambda r: r["answers"].__setitem__(0, {"type": "refusal", "name": "durable"}),
         "refused to answer 'durable'"),
        (lambda r: r["answers"][2].update(choice="banana"), "unknown option"),
        (lambda r: r["answers"][0].update(probability=1.7), "not a probability"),
        (lambda r: r["answers"][0].pop("probability"), "malformed"),
        (lambda r: r["answers"][0].update(type="choice"), "expected a predicate"),
        (lambda r: r["answers"][1]["probabilities"].append(
            {"value": 7, "label": "Extreme", "probability": 0.1}), "unknown score level"),
    ],
)
def test_parse_response_errors(mutate: Any, msg: str) -> None:
    data = json.loads(json.dumps(RESPONSE))
    mutate(data)
    with pytest.raises(JudgeError, match=msg):
        parse_response(QS, data)


def _judge(handler: Any, **kw: Any) -> OpenAIDecisionsJudge:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIDecisionsJudge(api_key="sk-test", client=client, backoff=0.0, **kw)


async def test_judge_success_sends_auth_and_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RESPONSE)

    result = await _judge(handler).judge("state", QS)
    assert result.model == "gpt-6-luna" and result.answers["type"].value == "fact"
    req = seen[0]
    assert str(req.url) == "https://api.openai.com/v1/decisions"
    assert req.headers["authorization"] == "Bearer sk-test"
    assert json.loads(req.content)["input"] == "state"


async def test_judge_retries_then_gives_up_with_provider_label() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, text="slow down")

    with pytest.raises(JudgeError, match="OpenAI returned HTTP 429"):
        await _judge(handler).judge("state", QS)
    assert calls["n"] == 3


async def test_judge_model_falls_back_when_response_omits_it() -> None:
    body = {"answers": RESPONSE["answers"]}
    result = await _judge(lambda r: httpx.Response(200, json=body)).judge("s", QS)
    assert result.model == "gpt-6-luna"


def test_env_config_ignores_memworthy_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example/v1/")
    monkeypatch.setenv("MEMWORTHY_MODEL", "jev-1.13.0")
    monkeypatch.delenv("OPENAI_DECISIONS_MODEL", raising=False)
    j = OpenAIDecisionsJudge()
    assert (j.api_key, j.base_url, j.model) == ("sk-env", "https://proxy.example/v1",
                                                "gpt-6-luna")
    monkeypatch.setenv("OPENAI_DECISIONS_MODEL", "gpt-6-luna-2026-10-01")
    assert OpenAIDecisionsJudge().model == "gpt-6-luna-2026-10-01"
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(JudgeError, match="OPENAI_API_KEY"):
        OpenAIDecisionsJudge()


async def test_recording_judge_stores_raw_openai_response(tmp_path: Any) -> None:
    fx = FixtureFile(tmp_path / "fx.json")
    recorder = RecordingJudge(_judge(lambda r: httpx.Response(200, json=RESPONSE)), fx)
    result = await recorder.judge("state", QS)
    assert recorder.model == "gpt-6-luna" and result.answers["durable"].value == 0.73
    [entry] = fx.entries.values()
    assert entry["raw"] == RESPONSE and entry["model"] == "gpt-6-luna"
    replay = await RecordedJudge(fx, model="gpt-6-luna").judge("state", QS)
    assert replay.answers == result.answers


async def test_refusal_sends_candidate_to_on_error_and_ledger() -> None:
    from memworthy import Candidate, DictStore, Gate, MemoryLedger

    def handler(request: httpx.Request) -> httpx.Response:
        answers: list[dict[str, Any]] = []
        for q in json.loads(request.content)["questions"]:
            if q["name"] == "sensitivity":
                answers.append({"type": "refusal", "name": q["name"]})  # real refusal shape
            elif q["type"] == "predicate":
                answers.append({"type": "predicate", "name": q["name"], "probability": 0.9})
            elif q["type"] == "choice":
                c = q["choices"][0]["value"]
                answers.append({"type": "choice", "name": q["name"], "choice": c,
                                "confidence": 0.9,
                                "probabilities": [{"value": c, "probability": 1.0}]})
            else:
                answers.append({"type": "score", "name": q["name"], "score": 0.0,
                                "confidence": 0.9, "probabilities": [
                                    {"value": 0, "label": q["levels"][0]["label"],
                                     "probability": 1.0}]})
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": answers})

    store, ledger = DictStore(), MemoryLedger()
    gate = Gate("personal-memory", store, judge=_judge(handler), ledger=ledger)
    [d] = await gate.aevaluate([Candidate.from_text("I have type 1 diabetes")])
    assert d.action == "review" and d.rule == "on_error"
    assert d.error == "judge refused to answer 'sensitivity'"
    assert len(list(ledger.read())) == 1 and await store.all() == []
