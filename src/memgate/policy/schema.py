"""Policy file models (YAML is parsed into these)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from memgate.models import Action, SourceRole


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelSignal(_Strict):
    """A question answered by the judge."""

    kind: Literal["noul", "choice", "score"]
    prompt: str
    options: dict[str, str] | None = None
    levels: list[str] | None = None
    applies_to: list[str] | None = None


class CheckSignal(_Strict):
    """A deterministic code check."""

    check: str
    args: dict[str, Any] = {}


class Rule(_Strict):
    """One ordered condition mapping signals to an action."""

    name: str | None = None
    when: str | None = None
    then: Action
    label: str | None = None
    restore: bool = False


class ConflictConfig(_Strict):
    """How existing memories are compared against a candidate."""

    k: int = Field(default=5, ge=1, le=20)
    enabled: bool = True
    prompt: str = "Which existing memory does the new information update or contradict?"


class PolicyTest(_Strict):
    """An example input with the expected action."""

    input: str
    role: SourceRole = "user"
    subject: str = "user"
    context: str = ""
    metadata: dict[str, Any] = {}
    source_text: str | None = None
    existing: list[str] = []
    expect: Action | list[Action]
    expect_type: str | None = None

    @property
    def expected(self) -> list[str]:
        """Accepted actions as a list."""
        return list(self.expect) if isinstance(self.expect, list) else [self.expect]


class SessionConfig(_Strict):
    """Episode splitting and noise filtering for session sources."""

    noise_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    min_user_words: int = Field(default=8, ge=1)
    gap_minutes: float = Field(default=30, gt=0)


class PolicySpec(_Strict):
    """A complete policy."""

    policy: str
    version: str
    description: str = ""
    types: dict[str, str]
    signals: dict[str, ModelSignal | CheckSignal] = {}
    rules: list[Rule]
    conflict: ConflictConfig = ConflictConfig()
    on_error: Action = "review"
    tests: list[PolicyTest] = []
    sessions: SessionConfig | None = None

    @field_validator("version", mode="before")
    @classmethod
    def _version_to_str(cls, v: Any) -> Any:
        return str(v) if isinstance(v, (int, float)) else v


def json_schema() -> dict[str, Any]:
    """JSON Schema for policy files, for editor autocompletion."""
    return PolicySpec.model_json_schema()
