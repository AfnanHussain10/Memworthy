"""MemGate: memory should be decided, not just extracted."""

from __future__ import annotations

import importlib
from typing import Any

from memgate.checks.registry import check, rule
from memgate.engine import RuleContext
from memgate.gate import Gate
from memgate.judges.base import Answer, Judge, JudgeError, JudgeResult, Question
from memgate.judges.mock import MockJudge
from memgate.judges.recorded import RecordedJudge
from memgate.ledger import JsonlLedger, MemoryLedger
from memgate.models import (
    Candidate,
    Decision,
    Episode,
    Memory,
    Patch,
    SignalValue,
    SourceRef,
    Turn,
)
from memgate.policy.loader import Policy, PolicyError, load_policy
from memgate.policy.schema import PolicySpec
from memgate.stores.dict import DictStore

__version__ = "0.1.0"

__all__ = [
    "Answer", "Candidate", "Decision", "DictStore", "Episode", "Gate", "GatedMemory",
    "JevJudge", "JsonlLedger", "Judge", "JudgeError", "JudgeResult", "MarkdownStore",
    "Memory", "MemoryLedger", "MockJudge", "Patch", "Policy", "PolicyError", "PolicySpec",
    "Question", "RecordedJudge", "RuleContext", "SignalValue", "SourceRef", "Turn",
    "check", "load_policy", "rule",
]


def __getattr__(name: str) -> Any:
    if name == "JevJudge":
        from memgate.judges.jev import JevJudge

        return JevJudge
    if name == "MarkdownStore":
        return importlib.import_module("memgate.stores.markdown").MarkdownStore
    if name in ("GatedMemory", "Mem0Store"):
        return getattr(importlib.import_module("memgate.stores.mem0"), name)
    raise AttributeError(f"module 'memgate' has no attribute {name!r}")
