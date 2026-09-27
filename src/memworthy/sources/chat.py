"""Chat messages as a candidate source."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from memworthy.models import Candidate, Episode, SourceRef, Turn, new_id

Extractor = Callable[[Episode], Awaitable[list[Candidate]]]
CONTEXT_MESSAGES = 3
_ROLES = {"user", "assistant", "tool", "system"}


def _role(value: Any) -> Any:
    return value if value in _ROLES else "unknown"


def _context(messages: list[dict[str, Any]], i: int) -> str:
    prev = messages[max(0, i - CONTEXT_MESSAGES):i]
    return "\n".join(f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in prev)


def split_messages(messages: list[dict[str, Any]], session_id: str | None = None,
                   subject: str = "user") -> list[Candidate]:
    """One candidate per user message, with the previous messages as context."""
    out: list[Candidate] = []
    for i, m in enumerate(messages):
        if m.get("role") != "user":
            continue
        text = str(m.get("content", "")).strip()
        if not text:
            continue
        out.append(Candidate(
            text=text,
            subject=str(m.get("subject", subject)),
            source=SourceRef(role="user", message_id=m.get("id"), session_id=session_id,
                             text=text),
            context=_context(messages, i),
            metadata=dict(m.get("metadata") or {}),
        ))
    return out


async def candidates_from_messages(messages: list[dict[str, Any]],
                                   extractor: Extractor | None = None,
                                   session_id: str | None = None) -> list[Candidate]:
    """Candidates from chat messages, via the extractor when one is given."""
    if extractor is None:
        return split_messages(messages, session_id)
    turns = [Turn(role=_role(m.get("role")), text=str(m.get("content", ""))) for m in messages]
    episode = Episode(id=new_id(), session_id=session_id or new_id(), turns=turns,
                      summary_text="\n".join(f"{t.role}: {t.text}" for t in turns))
    return await extractor(episode)
