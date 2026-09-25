"""A parsed coding-agent session, independent of the tool that wrote it."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from memgate.models import Turn

log = logging.getLogger("memgate.sources")
Tool = Literal["claude_code", "codex"]


@dataclass
class ParsedSession:
    """Normalized turns plus the facts needed to name and version the session."""

    id: str
    tool: Tool
    path: str
    turns: list[Turn] = field(default_factory=list)
    version: str | None = None
    cwd: str | None = None

    @property
    def project(self) -> str:
        """Working-directory name, used as the subject of candidates."""
        return Path(self.cwd).name if self.cwd else "project"


def parse_time(value: Any) -> datetime | None:
    """Parse an ISO timestamp, returning None when absent or malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL records, skipping blank or malformed lines with a debug log."""
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                log.debug("%s:%d: skipping malformed JSON line", path, n)
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def detect_format(records: list[dict[str, Any]]) -> Tool | None:
    """Guess the tool from record shapes."""
    for rec in records[:50]:
        if rec.get("type") in ("session_meta", "response_item", "turn_context"):
            return "codex"
        if "sessionId" in rec or rec.get("type") in ("user", "assistant", "summary"):
            return "claude_code"
    return None
