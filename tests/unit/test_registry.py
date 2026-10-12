from __future__ import annotations

import sys
import types
from importlib.metadata import EntryPoint
from typing import Any

import pytest

from memworthy import DictStore, Gate, MemoryLedger
from memworthy.judges import registry
from memworthy.judges.base import JudgeError, JudgeResult, Question
from memworthy.judges.jev import JevJudge
from memworthy.judges.mock import MockJudge
from memworthy.judges.openai_decisions import OpenAIDecisionsJudge


class PluginJudge:
    name = "plugin"

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        return JudgeResult(answers={})


def _broken() -> Any:
    raise RuntimeError("no config")


@pytest.fixture
def plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake plugin module and entry points for the memworthy.judges group."""
    mod = types.ModuleType("fake_judges")
    mod.PluginJudge = PluginJudge  # type: ignore[attr-defined]
    mod.Factories = types.SimpleNamespace(make=PluginJudge)  # type: ignore[attr-defined]
    mod.not_a_judge = lambda: object()  # type: ignore[attr-defined]
    mod.broken = _broken  # type: ignore[attr-defined]
    mod.constant = 3  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_judges", mod)
    eps = [EntryPoint(name, value, registry.ENTRY_POINT_GROUP) for name, value in [
        ("plugin", "fake_judges:PluginJudge"),
        ("dotted", "fake_judges:Factories.make"),
        ("jev", "fake_judges:PluginJudge"),
        ("bogus", "fake_judges:not_a_judge"),
        ("broken", "fake_judges:broken"),
        ("constant", "fake_judges:constant"),
        ("missing", "no_such_module_xyz:Judge"),
    ]]
    monkeypatch.setattr(registry, "entry_points", lambda group: eps)


def test_builtins_are_available() -> None:
    names = registry.available_judges()
    assert names["jev"].endswith("JevJudge")
    assert names["openai"].endswith("OpenAIDecisionsJudge")


def test_get_judge_builds_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert isinstance(registry.get_judge("jev"), JevJudge)
    assert isinstance(registry.get_judge("openai"), OpenAIDecisionsJudge)


def test_default_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMWORTHY_JUDGE", raising=False)
    assert registry.default_judge_name() == "jev"
    monkeypatch.setenv("MEMWORTHY_JUDGE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert isinstance(registry.get_judge(), OpenAIDecisionsJudge)
    gate = Gate("personal-memory", DictStore(), ledger=MemoryLedger())
    assert gate.judge.name == "openai"


def test_explicit_judge_skips_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMWORTHY_JUDGE", "nope")
    gate = Gate("personal-memory", DictStore(), judge=MockJudge(), ledger=MemoryLedger())
    assert gate.judge.name == "mock"


def test_missing_key_is_a_judge_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="OPENAI_API_KEY"):
        registry.get_judge("openai")


def test_unknown_judge_lists_available() -> None:
    with pytest.raises(JudgeError, match=r"unknown judge 'gpt'.*jev, microsoft, openai"):
        registry.get_judge("gpt")


@pytest.mark.usefixtures("plugins")
def test_plugins_load_and_cannot_shadow_builtins(caplog: pytest.LogCaptureFixture) -> None:
    names = registry.available_judges()
    assert names["jev"] == registry.BUILTIN_JUDGES["jev"]
    assert "ignored: the name is built in" in caplog.text
    assert isinstance(registry.get_judge("plugin"), PluginJudge)
    assert isinstance(registry.get_judge("dotted"), PluginJudge)


@pytest.mark.usefixtures("plugins")
@pytest.mark.parametrize("name,msg", [
    ("bogus", "does not implement the Judge protocol"),
    ("broken", "failed to start: no config"),
    ("constant", "is not callable"),
    ("missing", "failed to load"),
])
def test_bad_plugins_raise_judge_error(name: str, msg: str) -> None:
    with pytest.raises(JudgeError, match=msg):
        registry.get_judge(name)
