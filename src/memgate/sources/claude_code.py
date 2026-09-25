"""Claude Code session parser (local JSONL under ~/.claude/projects).

Built from scrubbed real sessions (Claude Code 2.1.251-2.1.281) in tests/fixtures/sessions.
The format is undocumented: unknown record and block types are skipped with a debug log.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memgate.models import Turn
from memgate.sources.session import ParsedSession, log, parse_time, read_jsonl

# User-role text that is harness chatter rather than something the person typed.
HARNESS_PREFIXES = ("<command-", "<local-command", "<system-reminder>", "Caveat:",
                    "[Request interrupted", "<bash-", "<user-prompt-submit-hook>",
                    "<task-notification>")


def is_person_text(text: str) -> bool:
    """True for text a person typed (not harness output or reminders)."""
    t = text.strip()
    return bool(t) and not t.startswith(HARNESS_PREFIXES)


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def parse_claude_code(path: str | Path) -> ParsedSession:
    """Parse one Claude Code session file into normalized turns."""
    p = Path(path)
    records = read_jsonl(p)
    session = ParsedSession(id=p.stem, tool="claude_code", path=str(p))
    tool_index: dict[str, int] = {}
    for rec in records:
        rtype = rec.get("type")
        session.version = rec.get("version") or session.version
        session.cwd = rec.get("cwd") or session.cwd
        if rec.get("sessionId"):
            session.id = str(rec["sessionId"])
        if rtype not in ("user", "assistant"):
            log.debug("claude_code: skipping record type %r", rtype)
            continue
        if rec.get("isSidechain") or rec.get("isMeta"):
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        ts = parse_time(rec.get("timestamp"))
        mid = rec.get("uuid")
        content = msg.get("content")
        if isinstance(content, str):
            if rtype == "user" and is_person_text(content):
                session.turns.append(Turn(role="user", text=content.strip(), timestamp=ts,
                                          message_id=mid))
            elif rtype == "assistant" and content.strip():
                session.turns.append(Turn(role="assistant", text=content.strip(),
                                          timestamp=ts, message_id=mid))
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = str(block.get("text", "")).strip()
                if rtype == "assistant" and text:
                    session.turns.append(Turn(role="assistant", text=text, timestamp=ts,
                                              message_id=mid))
                elif rtype == "user" and is_person_text(text):
                    session.turns.append(Turn(role="user", text=text, timestamp=ts,
                                              message_id=mid))
            elif btype == "tool_use" and rtype == "assistant":
                tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                tool_index[str(block.get("id"))] = len(session.turns)
                session.turns.append(Turn(role="tool", tool_name=str(block.get("name")),
                                          tool_input=tool_input, timestamp=ts, message_id=mid))
            elif btype == "tool_result" and rtype == "user":
                idx = tool_index.get(str(block.get("tool_use_id")))
                if idx is None:
                    continue
                session.turns[idx] = session.turns[idx].model_copy(update={
                    "tool_output": _result_text(block.get("content")),
                    "tool_error": bool(block.get("is_error")),
                })
            else:
                log.debug("claude_code: skipping block type %r", btype)
    return session
