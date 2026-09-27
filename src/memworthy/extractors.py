"""Optional extractor hook: turn an episode into candidate entries with any chat LLM.

Works with Memworthy's small OpenAI-compatible HTTP client (for example OpenRouter) or any
client exposing ``chat.completions.create`` (sync or async), such as the ``openai`` SDK.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from memworthy.models import Candidate, Episode, SourceRef
from memworthy.sources.pipeline import default_candidates, episode_metadata

log = logging.getLogger("memworthy.extractors")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
Extractor = Callable[[Episode], Awaitable[list[Candidate]]]

TYPE_GUIDE = {
    "task": "what was done and why, the files involved and the final status",
    "fix": "the problem's symptoms, its cause, and the change that resolved it",
    "decision": "the choice made, the reasoning, and the alternatives that were rejected",
    "discussion": "the conclusions and trade-offs reached, or the open question left",
    "explanation": "how the part of the codebase works, naming the source files it is based on",
    "concept": "the general technical insight, only if it is specific to this project",
    "convention": "the rule or preference for how work is done in this project",
}
SYSTEM = ("You turn a coding-agent session episode into knowledge-base entries. Write each "
          "entry as one or two plain sentences a developer could read in a month without the "
          "transcript. Never copy secrets, tokens or passwords. Reply with JSON only: "
          '{"entries": [{"text": "...", "referenced_files": ["path", ...]}]}. '
          "Return at most {max} entries; return an empty list if nothing is worth keeping.")


class OpenAICompatibleClient:
    """Minimal async client for OpenAI-compatible ``/chat/completions`` endpoints."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Point at ``base_url`` (for example https://openrouter.ai/api/v1)."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    async def complete(self, model: str, messages: list[dict[str, str]],
                       temperature: float = 0.0) -> str:
        """Return the first choice's message content."""
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "messages": messages, "temperature": temperature},
            )
        resp.raise_for_status()
        data = resp.json()
        return str(data["choices"][0]["message"]["content"] or "")


async def _complete(client: Any, model: str, messages: list[dict[str, str]]) -> str:
    if hasattr(client, "complete"):
        return str(await client.complete(model, messages))
    result = client.chat.completions.create(model=model, messages=messages, temperature=0)
    if inspect.isawaitable(result):
        result = await result
    return str(result.choices[0].message.content or "")


def parse_entries(raw: str) -> list[dict[str, Any]]:
    """Parse the model's JSON reply, tolerating code fences and surrounding prose."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in extractor reply")
    data = json.loads(text[start:end + 1])
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError("extractor reply has no 'entries' list")
    return [e for e in entries if isinstance(e, dict) and str(e.get("text", "")).strip()]


def llm_extractor(client: Any, model: str, max_entries: int = 3) -> Extractor:
    """Build an Extractor that asks a chat model for per-type knowledge entries."""

    async def extract(episode: Episode) -> list[Candidate]:
        guide = TYPE_GUIDE.get(episode.episode_type or "", "what is worth remembering")
        user = (f"Episode type: {episode.episode_type or 'unknown'}\n"
                f"For this type, capture {guide}.\nOutcome: {episode.outcome}\n"
                f"Files read: {', '.join(episode.files_read[:30])}\n"
                f"Files edited: {', '.join(episode.files_edited[:30])}\n\n"
                f"Transcript:\n{episode.summary_text}")
        messages = [{"role": "system", "content": SYSTEM.replace("{max}", str(max_entries))},
                    {"role": "user", "content": user}]
        try:
            entries = parse_entries(await _complete(client, model, messages))
        except Exception as exc:
            log.warning("extractor failed for episode %s (%s); using default", episode.id, exc)
            return default_candidates(episode)
        request = next((t for t in episode.turns if t.role == "user" and t.text), None)
        out = []
        for i, e in enumerate(entries[:max_entries]):
            refs = [str(f) for f in e.get("referenced_files") or []]
            out.append(Candidate(
                id=f"{episode.id}-{i}", text=str(e["text"]).strip(), subject=episode.project,
                source=SourceRef(role="user", session_id=episode.session_id,
                                 message_id=request.message_id if request else None,
                                 text=(request.text if request else "")[:1500]),
                context=episode.summary_text, metadata=episode_metadata(episode, refs)))
        return out

    return extract


def openrouter_extractor_from_env(max_entries: int = 3) -> Extractor:
    """LLM extractor using OPENROUTER_API_KEY and EXTRACTOR_MODEL from the environment."""
    key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("EXTRACTOR_MODEL")
    if not key or not model:
        raise RuntimeError("OPENROUTER_API_KEY and EXTRACTOR_MODEL must be set")
    client = OpenAICompatibleClient(os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
                                    key)
    return llm_extractor(client, model, max_entries)
