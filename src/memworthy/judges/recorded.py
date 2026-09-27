"""Replay judge answers from fixture files, and record them from a live judge."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from memworthy.judges.base import (
    Answer,
    Judge,
    JudgeError,
    JudgeResult,
    Question,
    validate_answers,
)

log = logging.getLogger("memworthy.judges.recorded")
FIXTURE_VERSION = 1


def fixture_key(state: str, questions: list[Question], model: str | None) -> str:
    """Stable hash of (state, questions, model) used to look up recorded answers."""
    payload = {
        "state": state,
        "questions": [q.model_dump(mode="json") for q in questions],
        "model": model,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def bundled_fixture_path(policy: str) -> Path | None:
    """Path of the recorded fixtures bundled for a template policy, if present."""
    p = resources.files("memworthy") / "templates" / "fixtures" / f"{policy}.json"
    return Path(str(p)) if p.is_file() else None


class FixtureFile:
    """In-memory view of a fixture file."""

    def __init__(self, path: str | Path | None = None, synthetic: bool = False) -> None:
        """Load ``path`` if it exists; otherwise start empty."""
        self.path = Path(path) if path is not None else None
        self.synthetic = synthetic
        self.entries: dict[str, dict[str, Any]] = {}
        if self.path is not None and self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("memworthy_fixtures") != FIXTURE_VERSION:
                raise JudgeError(f"{self.path}: not a memworthy fixture file")
            self.synthetic = bool(data.get("synthetic", False))
            self.entries = dict(data.get("entries") or {})

    def save(self) -> None:
        """Write atomically (temp file, then rename)."""
        if self.path is None:
            raise JudgeError("fixture file has no path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "memworthy_fixtures": FIXTURE_VERSION,
            "synthetic": self.synthetic,
            "entries": dict(sorted(self.entries.items())),
        }
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)


class RecordedJudge:
    """Replays answers keyed by hash of (state, questions, model).

    A missing entry raises JudgeError unless a ``fallback`` judge is given.
    """

    name = "recorded"

    def __init__(
        self,
        fixtures: str | Path | FixtureFile,
        model: str | None = None,
        fallback: Judge | None = None,
    ) -> None:
        """Load fixtures; ``model`` defaults to MEMWORTHY_MODEL or jev-1.13.0."""
        self.fixtures = fixtures if isinstance(fixtures, FixtureFile) else FixtureFile(fixtures)
        self.model = model or os.environ.get("MEMWORTHY_MODEL") or "jev-1.13.0"
        self.fallback = fallback
        self.misses: list[str] = []

    @property
    def synthetic(self) -> bool:
        """True when the fixtures were hand-authored rather than recorded."""
        return self.fixtures.synthetic

    def has(self, state: str, questions: list[Question]) -> bool:
        """True when an answer is recorded for this state and question set."""
        return fixture_key(state, questions, self.model) in self.fixtures.entries

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Return the recorded answers, or defer to the fallback judge."""
        key = fixture_key(state, questions, self.model)
        entry = self.fixtures.entries.get(key)
        if entry is None:
            self.misses.append(key)
            if self.fallback is not None:
                return await self.fallback.judge(state, questions)
            raise JudgeError(f"no recorded answer for this state (key {key[:12]})")
        answers = {k: Answer.model_validate(v) for k, v in entry["answers"].items()}
        validate_answers(questions, answers)
        return JudgeResult(answers=answers, model=entry.get("model"),
                           latency_ms=int(entry.get("latency_ms", 0)))


class RecordingJudge:
    """Wraps a live judge and stores each answer in a fixture file."""

    def __init__(self, inner: Judge, fixtures: str | Path | FixtureFile,
                 model: str | None = None) -> None:
        """Record answers from ``inner`` into ``fixtures`` keyed for ``model``."""
        self.inner = inner
        self.name = inner.name
        self.fixtures = fixtures if isinstance(fixtures, FixtureFile) else FixtureFile(fixtures)
        self.fixtures.synthetic = False
        self.model = model or getattr(inner, "model", None) or "jev-1.13.0"
        self.recorded = 0

    async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
        """Call the inner judge (unless already recorded) and store the result."""
        key = fixture_key(state, questions, self.model)
        entry = self.fixtures.entries.get(key)
        if entry is not None:
            answers = {k: Answer.model_validate(v) for k, v in entry["answers"].items()}
            return JudgeResult(answers=answers, model=entry.get("model"),
                               latency_ms=int(entry.get("latency_ms", 0)))
        raw: dict[str, Any] | None = None
        raw_fn = getattr(self.inner, "raw", None)
        if raw_fn is not None:
            from memworthy.judges.jev import parse_response

            raw, latency = await raw_fn(state, questions)
            answers = parse_response(questions, raw)
            result = JudgeResult(answers=answers, model=str(raw.get("model") or self.model),
                                 latency_ms=latency)
        else:
            result = await self.inner.judge(state, questions)
        self.fixtures.entries[key] = {
            "state": state,
            "questions": [q.model_dump(mode="json") for q in questions],
            "model": result.model,
            "answers": {k: a.model_dump(mode="json") for k, a in result.answers.items()},
            "raw": raw,
            "latency_ms": result.latency_ms,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.recorded += 1
        return result
