"""Split normalized session turns into episodes and derive their facts."""

from __future__ import annotations

import hashlib
import re
import shlex
from datetime import timedelta
from typing import Any

from memgate.models import Episode, Outcome, Turn
from memgate.sources.session import ParsedSession

READ_TOOLS = frozenset({"Read", "View", "NotebookRead", "view_image"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_KEYS = ("command", "cmd")
TEST_RE = re.compile(r"\b(pytest|py\.test|npm (?:run )?test|yarn test|pnpm test|vitest|jest|"
                     r"go test|cargo test|make test|tox|nox|rspec|phpunit)\b")
BUILD_RE = re.compile(r"\b(tsc|npm run build|yarn build|pnpm build|cargo build|go build|"
                      r"make\b|mvn (?:package|compile)|gradle build|docker build|next build)")
COMMIT_RE = re.compile(r"\bgit commit\b")
READ_CMD_RE = re.compile(r"^\s*(?:cat|nl -ba|head|tail|less|sed -n\s+'[^']*')\s+(.+)$")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
AFFIRMATIVE_RE = re.compile(r"^\s*(yes|yep|yeah|ok(?:ay)?|great|perfect|thanks|thank you|"
                            r"works|lgtm|nice|good|looks good|cool|awesome|done|we good)\b",
                            re.IGNORECASE)
ASSISTANT_CHARS = 400
OUTPUT_LINES = 20
MAX_SUMMARY = 12000


def shell_command(turn: Turn) -> str | None:
    """The shell command a tool turn ran, if any."""
    inp = turn.tool_input or {}
    for key in SHELL_KEYS:
        value = inp.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
    return None


def _paths_from_read_command(cmd: str) -> list[str]:
    out = []
    for part in re.split(r"&&|\|\||;|\|", cmd):
        m = READ_CMD_RE.match(part)
        if not m:
            continue
        try:
            args = shlex.split(m.group(1))
        except ValueError:
            continue
        out += [a for a in args if not a.startswith("-") and ("." in a or "/" in a)]
    return out


def files_read(turns: list[Turn]) -> list[str]:
    """Paths from read or view tool calls and read-only shell commands."""
    out: list[str] = []
    for t in turns:
        if t.tool_name in READ_TOOLS:
            path = (t.tool_input or {}).get("file_path") or (t.tool_input or {}).get("path")
            if isinstance(path, str):
                out.append(path)
        cmd = shell_command(t)
        if cmd:
            out += _paths_from_read_command(cmd)
    return list(dict.fromkeys(out))


def files_edited(turns: list[Turn]) -> list[str]:
    """Paths from edit or write tool calls and Codex patches."""
    out: list[str] = []
    for t in turns:
        inp: dict[str, Any] = t.tool_input or {}
        if t.tool_name in EDIT_TOOLS and isinstance(inp.get("file_path"), str):
            out.append(inp["file_path"])
        if t.tool_name == "apply_patch":
            patch = inp.get("input") or inp.get("patch") or ""
            out += [p.strip() for p in PATCH_FILE_RE.findall(str(patch))]
    return list(dict.fromkeys(out))


def outcome(turns: list[Turn]) -> Outcome:
    """Committed > last test > last build > user confirmed; a failing last check is failed."""
    shell = [(c, t.tool_error) for t in turns if (c := shell_command(t))]
    if any(COMMIT_RE.search(c) and not err for c, err in shell):
        return "committed"
    tests = [err for c, err in shell if TEST_RE.search(c)]
    if tests:
        return "failed" if tests[-1] else "tests_passed"
    builds = [err for c, err in shell if BUILD_RE.search(c)]
    if builds:
        return "failed" if builds[-1] else "build_passed"
    users = [t.text for t in turns if t.role == "user"]
    if len(users) > 1 and AFFIRMATIVE_RE.match(users[-1]) and len(users[-1].split()) < 8:
        return "user_confirmed"
    return "unknown"


def _trim_output(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 2 * OUTPUT_LINES:
        return text
    skipped = len(lines) - 2 * OUTPUT_LINES
    return "\n".join([*lines[:OUTPUT_LINES], f"[... {skipped} lines ...]",
                      *lines[-OUTPUT_LINES:]])


def summarize(turns: list[Turn]) -> str:
    """Condensed transcript: user text in full, assistant text truncated, tools reduced."""
    parts: list[str] = []
    for t in turns:
        if t.role == "user":
            parts.append(f"User: {t.text}")
        elif t.role == "assistant":
            text = t.text if len(t.text) <= ASSISTANT_CHARS else t.text[:ASSISTANT_CHARS] + "..."
            parts.append(f"Assistant: {text}")
        elif t.tool_name:
            cmd = shell_command(t)
            inp = t.tool_input or {}
            detail = cmd or inp.get("file_path") or inp.get("path") or ""
            if t.tool_name == "apply_patch":
                detail = ", ".join(PATCH_FILE_RE.findall(str(inp.get("input", ""))))
            status = " (error)" if t.tool_error else ""
            parts.append(f"Tool {t.tool_name}{status}: {str(detail)[:300]}")
            if t.tool_output and t.tool_name not in READ_TOOLS:
                parts.append(_trim_output(t.tool_output.strip())[:1500])
    text = "\n".join(parts)
    if len(text) > MAX_SUMMARY:
        half = MAX_SUMMARY // 2
        text = text[:half] + "\n[... transcript truncated ...]\n" + text[-half:]
    return text


def _starts_episode(turn: Turn, prev: Turn | None, min_words: int, gap: timedelta) -> bool:
    if prev is not None and turn.timestamp and prev.timestamp and \
            turn.timestamp - prev.timestamp > gap:
        return True
    return turn.role == "user" and len(turn.text.split()) >= min_words


def split_episodes(session: ParsedSession, min_user_words: int = 8,
                   gap_minutes: float = 30) -> list[Episode]:
    """Split at substantive user messages or long pauses; short replies stay attached."""
    gap = timedelta(minutes=gap_minutes)
    groups: list[list[Turn]] = []
    prev: Turn | None = None
    for turn in session.turns:
        if not groups or _starts_episode(turn, prev, min_user_words, gap):
            groups.append([])
        groups[-1].append(turn)
        prev = turn
    episodes = []
    for i, turns in enumerate(groups):
        if not any(t.role == "user" for t in turns) and not any(t.tool_name for t in turns):
            continue
        stamps = [t.timestamp for t in turns if t.timestamp]
        eid = hashlib.sha256(f"{session.id}:{i}".encode()).hexdigest()[:16]
        episodes.append(Episode(
            id=eid, session_id=session.id, turns=turns, files_read=files_read(turns),
            files_edited=files_edited(turns),
            commands=[c for t in turns if (c := shell_command(t))],
            outcome=outcome(turns), summary_text=summarize(turns),
            started_at=min(stamps) if stamps else None,
            ended_at=max(stamps) if stamps else None, project=session.project))
    return episodes
