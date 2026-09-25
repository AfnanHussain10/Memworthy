"""Pydantic data models shared across MemGate.

All models are frozen and serialize to JSON without custom encoders.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceRole = Literal["user", "assistant", "tool", "system", "unknown"]
Action = Literal[
    "store", "update", "merge", "supersede", "reject", "review", "redact", "store_labeled"
]
ACTIONS: tuple[str, ...] = (
    "store", "update", "merge", "supersede", "reject", "review", "redact", "store_labeled"
)
Outcome = Literal[
    "tests_passed", "build_passed", "committed", "user_confirmed", "failed", "unknown"
]


def new_id() -> str:
    """Return a new uuid4 hex id."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceRef(_Frozen):
    """Where a candidate came from."""

    role: SourceRole
    message_id: str | None = None
    session_id: str | None = None
    text: str


class Candidate(_Frozen):
    """A proposed memory, not yet decided."""

    id: str = Field(default_factory=new_id)
    text: str
    subject: str = "user"
    source: SourceRef
    context: str = ""
    metadata: dict[str, Any] = {}

    @classmethod
    def from_text(cls, text: str, role: SourceRole = "user", **fields: Any) -> Candidate:
        """Build a candidate whose source text is the candidate text itself."""
        return cls(text=text, source=SourceRef(role=role, text=text), **fields)


class Memory(_Frozen):
    """A stored memory."""

    id: str
    text: str
    type: str
    subject: str = "user"
    created_at: datetime
    updated_at: datetime
    sources: list[SourceRef] = []
    labels: list[str] = []
    metadata: dict[str, Any] = {}


class SignalValue(_Frozen):
    """One evaluated signal: a model answer or a code check result."""

    name: str
    kind: Literal["noul", "choice", "score", "check"]
    value: float | str | bool
    probabilities: dict[str, float] | None = None
    confidence: float | None = None


class Patch(_Frozen):
    """Text change applied to an existing memory."""

    target_id: str
    old_text: str
    new_text: str
    restore: bool = False


class Decision(_Frozen):
    """The outcome of gating one candidate, with everything needed to explain it."""

    id: str = Field(default_factory=new_id)
    candidate: Candidate
    action: Action
    type: str
    signals: dict[str, SignalValue | None]
    rule: str
    labels: list[str] = []
    target: Memory | None = None
    patch: Patch | None = None
    redacted_text: str | None = None
    policy: str
    policy_version: str
    judge: str
    model: str | None = None
    error: str | None = None
    warnings: list[str] = []
    questions_hash: str | None = None
    latency_ms: int
    created_at: datetime = Field(default_factory=utcnow)


class Turn(_Frozen):
    """One normalized record from a coding-agent session."""

    role: SourceRole
    text: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    tool_error: bool = False
    timestamp: datetime | None = None
    message_id: str | None = None


class Episode(_Frozen):
    """A span of a session that starts at a substantive user message."""

    id: str
    session_id: str
    turns: list[Turn]
    files_read: list[str] = []
    files_edited: list[str] = []
    commands: list[str] = []
    outcome: Outcome = "unknown"
    summary_text: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    episode_type: str | None = None
    project: str = "project"
