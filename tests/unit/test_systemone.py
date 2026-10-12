from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from memworthy.judges import registry
from memworthy.judges.base import JudgeError, Question
from memworthy.judges.foundry import FoundryDecisionJudge, discover_deployment, foundry_base_url
from memworthy.judges.jev import JevJudge
from memworthy.judges.systemone import SystemOneJudge

QS = [
    Question(name="type", kind="choice", prompt="What kind?",
             options={"fact": "A fact", "temporary": "Short-lived"}),
    Question(name="durable", kind="noul", prompt="Still true in a year?"),
    Question(name="sensitivity", kind="score", prompt="How sensitive?",
             levels=["Not sensitive", "Personal", "Highly sensitive"]),
]
# System One answer shapes (as Jev returns them); Microsoft's docs show no response body yet.
ANSWERS = {
    "type": {"type": "choice", "choice": "fact", "confidence": 0.93,
             "probabilities": {"fact": 0.96, "temporary": 0.04}},
    "durable": {"type": "noul", "noul": 0.73},
    "sensitivity": {"type": "score", "score": 0.88, "confidence": 0.82,
                    "probabilities": {"0": 0.12, "1": 0.88, "2": 0.0}},
}
ENV = {"AZURE_FOUNDRY_ENDPOINT": "https://res.services.ai.azure.com/",
       "AZURE_FOUNDRY_API_KEY": "azkey_test", "AZURE_FOUNDRY_DEPLOYMENT": "my-decision-1"}


def _capture(seen: list[httpx.Request], model: str = "microsoft-decision-1") -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"model": model, "answers": ANSWERS})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def foundry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)


@pytest.mark.parametrize("auth,header,value", [
    ("bearer", "authorization", "Bearer k"), ("api-key", "api-key", "k")])
async def test_systemone_auth_styles(auth: Any, header: str, value: str) -> None:
    seen: list[httpx.Request] = []
    j = SystemOneJudge(api_key="k", base_url="https://gw.example/v1/", model="m", auth=auth,
                       client=_capture(seen))
    await j.judge("s", QS)
    assert str(seen[0].url) == "https://gw.example/v1/systemone"
    assert seen[0].headers[header] == value
    other = "api-key" if header == "authorization" else "authorization"
    assert other not in seen[0].headers


def test_systemone_needs_a_key() -> None:
    with pytest.raises(JudgeError, match="System One judge needs an API key"):
        SystemOneJudge(api_key="", base_url="https://gw.example/v1", model="m")


def test_jev_is_a_systemone_preset() -> None:
    j = JevJudge(api_key="apikey_test")
    assert isinstance(j, SystemOneJudge)
    assert (j.name, j.label, j.auth, j.base_url) == ("jev", "Jev", "bearer",
                                                      "https://api.typesafe.ai/v1")


@pytest.mark.parametrize("endpoint", [
    "https://res.services.ai.azure.com", "https://res.services.ai.azure.com/",
    "https://res.services.ai.azure.com/providers/microsoft/v1",
    "https://res.services.ai.azure.com/providers/microsoft/v1/",
    "https://res.services.ai.azure.com/providers/microsoft/v1/systemone"])
def test_foundry_base_url(endpoint: str) -> None:
    assert foundry_base_url(endpoint) == (
        "https://res.services.ai.azure.com/providers/microsoft/v1")


@pytest.mark.usefixtures("foundry_env")
async def test_foundry_request_uses_deployment_and_api_key() -> None:
    seen: list[httpx.Request] = []
    j = FoundryDecisionJudge(client=_capture(seen), backoff=0.0)
    result = await j.judge("state", QS)
    req = seen[0]
    assert str(req.url) == ("https://res.services.ai.azure.com/providers/microsoft/v1/"
                            "systemone")
    assert req.headers["api-key"] == "azkey_test" and "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "my-decision-1" and body["state"] == "state"
    assert body["questions"]["durable"] == {"type": "noul",
                                            "instructions": "Still true in a year?"}
    # The response names the underlying model, not the deployment.
    assert result.model == "microsoft-decision-1"
    assert result.answers["sensitivity"].probabilities == {
        "Not sensitive": 0.12, "Personal": 0.88, "Highly sensitive": 0.0}


@pytest.mark.usefixtures("foundry_env")
async def test_foundry_errors_name_the_provider() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(422, json={"error": "unknown deployment"})))
    with pytest.raises(JudgeError, match="Microsoft Foundry returned HTTP 422"):
        await FoundryDecisionJudge(client=client).judge("s", QS)


@pytest.mark.parametrize("missing", ["AZURE_FOUNDRY_ENDPOINT", "AZURE_FOUNDRY_API_KEY"])
def test_foundry_reports_every_missing_setting(monkeypatch: pytest.MonkeyPatch,
                                               missing: str) -> None:
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing)
    with pytest.raises(JudgeError, match=missing):
        FoundryDecisionJudge()


def test_foundry_arguments_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    j = FoundryDecisionJudge(endpoint="https://other.example", api_key="k2", deployment="d2")
    assert (j.base_url, j.api_key, j.model) == (
        "https://other.example/providers/microsoft/v1", "k2", "d2")


@pytest.mark.usefixtures("foundry_env")
def test_registry_builds_microsoft() -> None:
    assert isinstance(registry.get_judge("microsoft"), FoundryDecisionJudge)


def _listing(rows: list[dict[str, Any]], status: int = 200,
             seen: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json={"data": rows, "object": "list"})
    return httpx.Client(transport=httpx.MockTransport(handler))


# Shape of a real listing (2026-10-12): id is the deployment name, model the catalog name.
ROWS = [{"id": "gpt-6-luna", "model": "gpt-6-luna", "status": "succeeded"},
        {"id": "Decision-1", "model": "Microsoft-Decision-1", "status": "succeeded"}]


def test_discover_finds_the_decision_deployment() -> None:
    seen: list[httpx.Request] = []
    name = discover_deployment(
        "https://res.services.ai.azure.com/providers/microsoft/v1/systemone", "k",
        client=_listing(ROWS, seen=seen))
    assert name == "Decision-1"
    assert str(seen[0].url) == ("https://res.services.ai.azure.com/openai/deployments"
                                "?api-version=2022-12-01")
    assert seen[0].headers["api-key"] == "k"


@pytest.mark.parametrize("rows,status,msg", [
    (ROWS[:1], 200, "found none"),
    ([*ROWS, {"id": "Decision-2", "model": "Microsoft-Decision-1", "status": "succeeded"}],
     200, "found Decision-1, Decision-2"),
    ([{**ROWS[1], "status": "creating"}], 200, "found none"),
    ([], 500, "HTTP 500"),
])
def test_discover_errors_ask_for_the_env_var(rows: list[dict[str, Any]], status: int,
                                             msg: str) -> None:
    with pytest.raises(JudgeError, match=f"{msg}.*AZURE_FOUNDRY_DEPLOYMENT"):
        discover_deployment("https://res.services.ai.azure.com", "k",
                            client=_listing(rows, status))


def test_foundry_discovers_deployment_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("AZURE_FOUNDRY_DEPLOYMENT")
    assert FoundryDecisionJudge(discovery_client=_listing(ROWS)).model == "Decision-1"


@pytest.mark.usefixtures("foundry_env")
def test_explicit_deployment_skips_discovery() -> None:
    seen: list[httpx.Request] = []
    j = FoundryDecisionJudge(discovery_client=_listing(ROWS, seen=seen))
    assert j.model == "my-decision-1" and seen == []


def test_discover_auth_failure_points_at_the_key() -> None:
    with pytest.raises(JudgeError, match="HTTP 401; check AZURE_FOUNDRY_API_KEY"):
        discover_deployment("https://res.services.ai.azure.com", "k",
                            client=_listing([], 401))
