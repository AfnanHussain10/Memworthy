from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from memgate.judges.base import JudgeError, Question, validate_answers
from memgate.judges.jev import JevJudge, build_request, parse_response
from memgate.judges.mock import MockJudge
from memgate.judges.recorded import (
    FixtureFile,
    RecordedJudge,
    RecordingJudge,
    fixture_key,
)

QS = [
    Question(name="type", kind="choice", prompt="What kind?",
             options={"fact": "A fact", "temporary": "Short-lived"}),
    Question(name="durable", kind="noul", prompt="Still true in a year?"),
    Question(name="sensitivity", kind="score", prompt="How sensitive?",
             levels=["Not sensitive", "Personal", "Highly sensitive"]),
]
# Shape copied from a real System One response (values rounded), see the spec's Jev section.
RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "type": {"type": "choice", "choice": "fact", "confidence": 0.93,
                 "probabilities": {"fact": 0.96, "temporary": 0.04}},
        "durable": {"type": "noul", "noul": 0.73},
        "sensitivity": {"type": "score", "score": 0.88, "confidence": 0.82,
                        "legend": {"0": "Not sensitive", "1": "Personal",
                                   "2": "Highly sensitive"},
                        "probabilities": {"0": 0.12, "1": 0.88, "2": 0.0}},
    },
    "usage": {"input_tokens": 385, "output_tokens": 64},
}


def test_build_request_shape() -> None:
    body = build_request("jev-1.13.0", "state text", QS)
    assert body == {
        "model": "jev-1.13.0",
        "state": "state text",
        "questions": {
            "type": {"type": "choice", "instructions": "What kind?",
                     "criteria": {"fact": "A fact", "temporary": "Short-lived"}},
            "durable": {"type": "noul", "instructions": "Still true in a year?"},
            "sensitivity": {"type": "score", "instructions": "How sensitive?",
                            "criteria": ["Not sensitive", "Personal", "Highly sensitive"]},
        },
    }


def test_parse_response_maps_score_levels() -> None:
    answers = parse_response(QS, RESPONSE)
    assert answers["type"].value == "fact" and answers["type"].confidence == 0.93
    assert answers["durable"].value == 0.73 and answers["durable"].confidence is None
    assert answers["sensitivity"].value == 0.88
    assert answers["sensitivity"].probabilities == {
        "Not sensitive": 0.12, "Personal": 0.88, "Highly sensitive": 0.0}


@pytest.mark.parametrize(
    "mutate,msg",
    [
        (lambda r: r.pop("answers"), "no 'answers'"),
        (lambda r: r["answers"].pop("durable"), "missing answer"),
        (lambda r: r["answers"]["type"].update(choice="banana"), "unknown option"),
        (lambda r: r["answers"]["durable"].update(noul=1.7), "not a probability"),
        (lambda r: r["answers"]["durable"].pop("noul"), "malformed"),
        (lambda r: r["answers"]["sensitivity"]["probabilities"].update({"7": 0.1}),
         "unknown score level"),
    ],
)
def test_parse_response_errors(mutate: Any, msg: str) -> None:
    data = json.loads(json.dumps(RESPONSE))
    mutate(data)
    with pytest.raises(JudgeError, match=msg):
        parse_response(QS, data)


def _judge(handler: Any, **kw: Any) -> JevJudge:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JevJudge(api_key="apikey_test", client=client, backoff=0.0, **kw)


async def test_jev_judge_success_sends_auth_and_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=RESPONSE)

    result = await _judge(handler).judge("state", QS)
    assert result.model == "jev-1.13.0" and result.answers["type"].value == "fact"
    req = seen[0]
    assert str(req.url) == "https://api.typesafe.ai/v1/systemone"
    assert req.headers["authorization"] == "Bearer apikey_test"
    assert json.loads(req.content)["model"] == "jev-1.13.0"


@pytest.mark.parametrize("status", [429, 500, 529])
async def test_jev_judge_retries_then_succeeds(status: int) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status if calls["n"] < 3 else 200, json=RESPONSE)

    await _judge(handler).judge("state", QS)
    assert calls["n"] == 3


async def test_jev_judge_gives_up_after_retries() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(529, text="overloaded")

    with pytest.raises(JudgeError, match="HTTP 529"):
        await _judge(handler).judge("state", QS)
    assert calls["n"] == 3


@pytest.mark.parametrize("status", [400, 401, 422])
async def test_jev_judge_no_retry_on_4xx(status: int) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"error": "bad"})

    with pytest.raises(JudgeError, match=f"HTTP {status}"):
        await _judge(handler).judge("state", QS)
    assert calls["n"] == 1


async def test_jev_judge_network_errors_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("down")

    with pytest.raises(JudgeError, match="ConnectError"):
        await _judge(handler).judge("state", QS)
    assert calls["n"] == 3


async def test_jev_judge_bad_json() -> None:
    with pytest.raises(JudgeError, match="invalid JSON"):
        await _judge(lambda r: httpx.Response(200, text="nope")).judge("s", QS)
    with pytest.raises(JudgeError, match="non-object"):
        await _judge(lambda r: httpx.Response(200, json=[1])).judge("s", QS)


def test_jev_env_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_env")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://gw.example/v1/")
    monkeypatch.setenv("MEMGATE_MODEL", "jev-9")
    j = JevJudge()
    assert (j.api_key, j.base_url, j.model) == ("apikey_env", "https://gw.example/v1", "jev-9")
    monkeypatch.delenv("TYPESAFE_API_KEY")
    with pytest.raises(JudgeError):
        JevJudge()


async def test_mock_judge_rules_and_defaults() -> None:
    j = MockJudge(defaults={"durable": 0.2},
                  rules=[("Dubai", {"type": "temporary", "sensitivity": 1.5})],
                  responder=lambda s, q: {"durable": 0.8} if "forever" in s else {})
    r = await j.judge("I am in Dubai forever", QS)
    assert r.answers["type"].value == "temporary"
    assert r.answers["durable"].value == 0.8
    assert r.answers["sensitivity"].value == 1.5
    assert r.answers["sensitivity"].probabilities == {
        "Not sensitive": 0.0, "Personal": 0.5, "Highly sensitive": 0.5}
    r = await j.judge("other", QS)
    assert r.answers["type"].value == "fact" and r.answers["durable"].value == 0.2
    r = await MockJudge(defaults={"sensitivity": "Personal", "type": {"temporary": 0.7,
                                                                     "fact": 0.3}}).judge("", QS)
    assert r.answers["sensitivity"].value == 1.0 and r.answers["type"].value == "temporary"
    with pytest.raises(JudgeError):
        await MockJudge(defaults={"sensitivity": "Nope"}).judge("", QS)
    assert len(j.calls) == 2


def test_validate_answers_score_not_number() -> None:
    from memgate.judges.base import Answer

    with pytest.raises(JudgeError, match="not a number"):
        validate_answers([QS[2]], {"sensitivity": Answer(name="sensitivity", value="x")})


async def test_record_then_replay(tmp_path: Path) -> None:
    path = tmp_path / "fx.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSE)

    rec = RecordingJudge(_judge(handler), path)
    first = await rec.judge("state A", QS)
    again = await rec.judge("state A", QS)  # served from the file, no second HTTP call
    assert rec.recorded == 1 and first.answers == again.answers
    rec.fixtures.save()
    data = json.loads(path.read_text())
    assert data["memgate_fixtures"] == 1 and data["synthetic"] is False
    [entry] = data["entries"].values()
    assert entry["raw"]["answers"]["durable"]["noul"] == 0.73

    replay = RecordedJudge(path)
    assert not replay.synthetic and replay.has("state A", QS)
    got = await replay.judge("state A", QS)
    assert got.answers == first.answers and got.model == "jev-1.13.0"
    with pytest.raises(JudgeError, match="no recorded answer"):
        await replay.judge("state B", QS)
    assert len(replay.misses) == 1
    fallback = RecordedJudge(path, fallback=MockJudge())
    assert (await fallback.judge("state B", QS)).model == "mock"


async def test_recording_wraps_non_jev_judge(tmp_path: Path) -> None:
    rec = RecordingJudge(MockJudge(), FixtureFile(tmp_path / "m.json"), model="m")
    await rec.judge("s", QS)
    assert rec.recorded == 1


def test_fixture_key_depends_on_all_parts() -> None:
    k = fixture_key("s", QS, "jev-1.13.0")
    assert k == fixture_key("s", QS, "jev-1.13.0")
    assert k != fixture_key("s2", QS, "jev-1.13.0")
    assert k != fixture_key("s", QS[:2], "jev-1.13.0")
    assert k != fixture_key("s", QS, "jev-2")


def test_fixture_file_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": 1}')
    with pytest.raises(JudgeError, match="not a memgate fixture"):
        FixtureFile(bad)
    with pytest.raises(JudgeError, match="no path"):
        FixtureFile().save()
