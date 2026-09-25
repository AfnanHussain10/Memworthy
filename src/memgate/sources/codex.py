"""Codex session parser (local JSONL rollouts under ~/.codex/sessions).

Built from scrubbed real sessions (Codex 0.107-0.130) in tests/fixtures/sessions.
Unknown record and payload types are skipped with a debug log.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from memgate.models import Turn
from memgate.sources.session import ParsedSession, log, parse_time, read_jsonl

# User-role messages Codex injects itself (instructions, environment, notices).
INJECTED_PREFIXES = ("<environment_context", "<permissions", "# AGENTS.md", "<user_instructions",
                     "<app-context", "<collaboration_mode", "<skills_instructions",
                     "<plugins_instructions", "<turn_aborted", "<user_shell_command",
                     "<subagent_notification", "<skill>")
FILES_REQUEST = "## My request for Codex:"
EXIT_RE = re.compile(r"(?:Process exited with code|Exit code:)\s*(-?\d+)")


def person_text(text: str) -> str | None:
    """The part of a user message the person typed, or None for injected content."""
    t = text.strip()
    if not t or t.startswith(INJECTED_PREFIXES):
        return None
    if FILES_REQUEST in t:
        t = t.split(FILES_REQUEST, 1)[1].strip()
    return t or None


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
        except ValueError:
            return {"input": raw}
        return val if isinstance(val, dict) else {"input": raw}
    return {}


def parse_output(raw: Any) -> tuple[str, bool]:
    """Return (output text, is_error) from a Codex tool output in any known shape."""
    text = raw if isinstance(raw, str) else json.dumps(raw) if raw is not None else ""
    code: int | None = None
    if isinstance(raw, str) and raw.lstrip().startswith("{"):
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            text = str(obj.get("output", text))
            meta = obj.get("metadata")
            if isinstance(meta, dict) and isinstance(meta.get("exit_code"), int):
                code = meta["exit_code"]
    if code is None:
        m = EXIT_RE.search(text)
        code = int(m.group(1)) if m else None
    return text, code is not None and code != 0


def parse_codex(path: str | Path) -> ParsedSession:
    """Parse one Codex rollout file into normalized turns."""
    p = Path(path)
    session = ParsedSession(id=p.stem, tool="codex", path=str(p))
    calls: dict[str, int] = {}
    for rec in read_jsonl(p):
        rtype = rec.get("type")
        raw_payload = rec.get("payload")
        payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
        ts = parse_time(rec.get("timestamp"))
        if rtype == "session_meta":
            session.id = str(payload.get("id") or session.id)
            session.version = payload.get("cli_version") or session.version
            session.cwd = payload.get("cwd") or session.cwd
            continue
        if rtype != "response_item":
            log.debug("codex: skipping record type %r", rtype)
            continue
        ptype = payload.get("type")
        if ptype == "message":
            role = payload.get("role")
            texts = [str(c.get("text", "")) for c in payload.get("content") or []
                     if isinstance(c, dict)]
            for text in texts:
                if role == "user":
                    typed = person_text(text)
                    if typed:
                        session.turns.append(Turn(role="user", text=typed, timestamp=ts,
                                                  message_id=payload.get("id")))
                elif role == "assistant" and text.strip():
                    session.turns.append(Turn(role="assistant", text=text.strip(),
                                              timestamp=ts, message_id=payload.get("id")))
        elif ptype in ("function_call", "custom_tool_call"):
            args = _args(payload.get("arguments") if ptype == "function_call"
                         else payload.get("input"))
            calls[str(payload.get("call_id"))] = len(session.turns)
            session.turns.append(Turn(role="tool", tool_name=str(payload.get("name")),
                                      tool_input=args, timestamp=ts,
                                      message_id=payload.get("id")))
        elif ptype in ("function_call_output", "custom_tool_call_output"):
            idx = calls.get(str(payload.get("call_id")))
            if idx is None:
                continue
            text, err = parse_output(payload.get("output"))
            session.turns[idx] = session.turns[idx].model_copy(
                update={"tool_output": text, "tool_error": err})
        else:
            log.debug("codex: skipping payload type %r", ptype)
    return session
