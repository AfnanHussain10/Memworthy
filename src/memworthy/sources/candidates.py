"""Plain candidate lists (JSON or JSONL) as a source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memworthy.models import Candidate, SourceRef


def candidate_from_dict(item: dict[str, Any]) -> Candidate:
    """Build a Candidate from ``{text, role?, subject?, context?, metadata?, source_text?}``."""
    text = str(item["text"])
    role = item.get("role", "user")
    fields: dict[str, Any] = {
        "text": text,
        "subject": item.get("subject", "user"),
        "context": item.get("context", ""),
        "metadata": dict(item.get("metadata") or {}),
        "source": SourceRef(role=role, text=str(item.get("source_text", text)),
                            message_id=item.get("message_id"),
                            session_id=item.get("session_id")),
    }
    if item.get("id"):
        fields["id"] = str(item["id"])
    return Candidate(**fields)


def load_candidates(path: str | Path) -> list[Candidate]:
    """Read candidates from a JSON array or a JSONL file."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        items = json.loads(text)
    else:
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [candidate_from_dict(i) for i in items]
