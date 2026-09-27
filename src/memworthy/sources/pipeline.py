"""Session pipeline: parse, split into episodes, drop noise, extract candidates."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from memworthy.judges.base import Judge, JudgeError, Question, validate_answers
from memworthy.models import Candidate, Episode, SourceRef
from memworthy.policy.loader import Policy
from memworthy.policy.schema import SessionConfig
from memworthy.sources.claude_code import parse_claude_code
from memworthy.sources.codex import parse_codex
from memworthy.sources.episodes import split_episodes
from memworthy.sources.session import ParsedSession, detect_format, read_jsonl

log = logging.getLogger("memworthy.sources.pipeline")
Extractor = Callable[[Episode], Awaitable[list[Candidate]]]
NOISE = "noise"
SUBSTANTIVE_WORDS = 12
NOISE_DESCRIPTION = "Setup, retries, small talk or raw output with no lasting value"
EPISODE_PROMPT = "What kind of work does this episode of a coding session mainly contain?"
PATH_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.[A-Za-z]{1,5})(?![\w/])")


def referenced_paths(text: str, known: list[str]) -> list[str]:
    """File paths named in ``text``; known session files are preferred when they match."""
    found = [m for m in PATH_RE.findall(text) if "/" in m or m in {k.split("/")[-1]
                                                                for k in known}]
    return list(dict.fromkeys(found))


@dataclass
class SessionIngest:
    """Everything the session pipeline produced, for reporting."""

    sessions: list[ParsedSession] = field(default_factory=list)
    episodes: list[Episode] = field(default_factory=list)
    dropped: list[Episode] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)


def session_files(path: str | Path) -> list[Path]:
    """All JSONL files under a folder (or the file itself), sorted."""
    p = Path(path).expanduser()
    if p.is_file():
        return [p]
    return sorted(q for q in p.rglob("*.jsonl") if q.is_file())


def parse_session(path: Path, fmt: str = "auto") -> ParsedSession | None:
    """Parse one file with the given or detected format; None if unrecognized."""
    tool = fmt if fmt in ("claude_code", "codex") else detect_format(read_jsonl(path))
    if tool == "claude_code":
        return parse_claude_code(path)
    if tool == "codex":
        return parse_codex(path)
    log.debug("skipping %s: not a Claude Code or Codex session", path)
    return None


def episode_state(ep: Episode) -> str:
    """State text used to classify an episode."""
    lines = [f"Coding session episode in project {ep.project}", f"Outcome: {ep.outcome}"]
    if ep.files_edited:
        lines.append("Files edited: " + ", ".join(ep.files_edited[:20]))
    lines += ["", "Transcript:", ep.summary_text]
    return "\n".join(lines)


def episode_question(policy: Policy) -> Question:
    """One choice over the policy's types plus noise."""
    options = dict(policy.spec.types)
    options.setdefault(NOISE, NOISE_DESCRIPTION)
    return Question(name="episode_type", kind="choice", prompt=EPISODE_PROMPT, options=options)


async def classify(policy: Policy, judge: Judge, ep: Episode) -> tuple[Episode, bool]:
    """Label the episode; return it and whether it is noise to drop."""
    cfg = policy.spec.sessions or SessionConfig()
    q = episode_question(policy)
    try:
        result = await judge.judge(episode_state(ep), [q])
        validate_answers([q], result.answers)
    except JudgeError as exc:
        log.warning("episode classification failed, keeping episode: %s", exc)
        return ep, False
    ans = result.answers["episode_type"]
    labeled = ep.model_copy(update={"episode_type": str(ans.value)})
    p_noise = (ans.probabilities or {}).get(NOISE, 0.0)
    return labeled, ans.value == NOISE and p_noise > cfg.noise_threshold


def default_candidates(ep: Episode) -> list[Candidate]:
    """Without an extractor: the first request and the final answer become one candidate."""
    request = next((t for t in ep.turns if t.role == "user" and t.text), None)
    answers = [t.text for t in ep.turns if t.role == "assistant" and t.text]
    # The final message is often a one-liner ("Committed as abc123."); prefer the last
    # substantive one.
    answer = next((a for a in reversed(answers) if len(a.split()) >= SUBSTANTIVE_WORDS),
                  answers[-1] if answers else "")
    if request is None or not answer:
        return []
    text = answer if len(answer) <= 600 else answer[:600] + "..."
    return [Candidate(
        id=f"{ep.id}-0", text=text, subject=ep.project,
        source=SourceRef(role="user", message_id=request.message_id, session_id=ep.session_id,
                         text=request.text[:1500]),
        context=ep.summary_text,
        metadata=episode_metadata(ep, referenced_paths(text, ep.files_read + ep.files_edited)
                                  or ep.files_edited))]


def episode_metadata(ep: Episode, referenced: list[str]) -> dict[str, object]:
    """Candidate metadata derived from an episode."""
    return {
        "episode_id": ep.id, "session_id": ep.session_id, "episode_type": ep.episode_type,
        "outcome": ep.outcome, "files_read": ep.files_read, "files_edited": ep.files_edited,
        "referenced_files": referenced, "files": referenced, "commands": ep.commands[:10],
        "timestamp": ep.ended_at.isoformat() if ep.ended_at else None,
    }


async def ingest_sessions(policy: Policy, judge: Judge, path: str | Path, fmt: str = "auto",
                          extractor: Extractor | None = None,
                          concurrency: int = 8) -> SessionIngest:
    """Run the whole session pipeline and report what happened at each stage."""
    cfg = policy.spec.sessions or SessionConfig()
    out = SessionIngest()
    for f in session_files(path):
        parsed = parse_session(f, fmt)
        if parsed is not None:
            out.sessions.append(parsed)
            out.episodes += split_episodes(parsed, cfg.min_user_words, cfg.gap_minutes)
    sem = asyncio.Semaphore(concurrency)

    async def one(ep: Episode) -> tuple[Episode, bool]:
        async with sem:
            return await classify(policy, judge, ep)

    labeled = await asyncio.gather(*(one(ep) for ep in out.episodes))
    out.episodes = [ep for ep, _ in labeled]
    kept = [ep for ep, noise in labeled if not noise]
    out.dropped = [ep for ep, noise in labeled if noise]
    for ep in kept:
        if extractor is None:
            out.candidates += default_candidates(ep)
        else:
            out.candidates += await extractor(ep)
    return out


async def session_candidates(policy: Policy, judge: Judge, path: str | Path, fmt: str,
                             extractor: Extractor | None = None) -> list[Candidate]:
    """Candidates from a folder of coding-agent sessions."""
    return (await ingest_sessions(policy, judge, path, fmt, extractor)).candidates
