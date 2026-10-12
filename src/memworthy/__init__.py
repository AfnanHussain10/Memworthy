"""Memworthy: memory should be decided, not just extracted."""

from __future__ import annotations

import importlib
from typing import Any

from memworthy.checks.registry import check, rule
from memworthy.engine import RuleContext
from memworthy.gate import Gate
from memworthy.judges.base import Answer, Judge, JudgeError, JudgeResult, Question
from memworthy.judges.mock import MockJudge
from memworthy.judges.recorded import RecordedJudge
from memworthy.judges.registry import available_judges, get_judge
from memworthy.ledger import JsonlLedger, MemoryLedger
from memworthy.models import (
    Candidate,
    Decision,
    Episode,
    Memory,
    Patch,
    SignalValue,
    SourceRef,
    Turn,
)
from memworthy.policy.loader import Policy, PolicyError, load_policy
from memworthy.policy.schema import PolicySpec
from memworthy.stores.dict import DictStore

__version__ = "0.2.0"

__all__ = [
    "Answer", "Candidate", "Decision", "DictStore", "Episode", "FoundryDecisionJudge", "Gate",
    "GatedMemory",
    "JevJudge", "JsonlLedger", "Judge", "JudgeError", "JudgeResult", "MarkdownStore",
    "Memory", "MemoryLedger", "MockJudge", "OpenAIDecisionsJudge", "Patch", "Policy",
    "PolicyError", "PolicySpec", "Question", "RecordedJudge", "RuleContext", "SignalValue",
    "SourceRef", "SystemOneJudge", "Turn",
    "available_judges", "check", "get_judge", "load_policy", "rule",
]


def __getattr__(name: str) -> Any:
    if name == "JevJudge":
        from memworthy.judges.jev import JevJudge

        return JevJudge
    if name == "SystemOneJudge":
        from memworthy.judges.systemone import SystemOneJudge

        return SystemOneJudge
    if name == "FoundryDecisionJudge":
        from memworthy.judges.foundry import FoundryDecisionJudge

        return FoundryDecisionJudge
    if name == "OpenAIDecisionsJudge":
        from memworthy.judges.openai_decisions import OpenAIDecisionsJudge

        return OpenAIDecisionsJudge
    if name == "MarkdownStore":
        return importlib.import_module("memworthy.stores.markdown").MarkdownStore
    if name in ("GatedMemory", "Mem0Store"):
        return getattr(importlib.import_module("memworthy.stores.mem0"), name)
    raise AttributeError(f"module 'memworthy' has no attribute {name!r}")
