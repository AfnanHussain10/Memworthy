from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from memworthy.extractors import (
    OpenAICompatibleClient,
    llm_extractor,
    openrouter_extractor_from_env,
    parse_entries,
)
from memworthy.models import Episode, Turn

EPISODE = Episode(
    id="ep1", session_id="s1", project="bookshelf", episode_type="decision",
    turns=[Turn(role="user", text="why cursors?", message_id="m1"),
           Turn(role="assistant", text="Cursor pagination is stable when rows are added and "
                "avoids slow offset scans on big tables.")],
    files_read=["app/routes/books.py"], outcome="committed", summary_text="User: why cursors?")
REPLY = json.dumps({"entries": [
    {"text": "Chose cursor pagination over offsets for stability.",
     "referenced_files": ["app/routes/books.py"]},
    {"text": "   "}]})


class Fake:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[Any] = []

    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        self.seen.append((model, messages))
        return self.reply


async def test_llm_extractor_builds_candidates() -> None:
    fake = Fake(f"Sure!\n```json\n{REPLY}\n```")
    [cand] = await llm_extractor(fake, "m")(EPISODE)
    assert cand.text == "Chose cursor pagination over offsets for stability."
    assert cand.subject == "bookshelf" and cand.id == "ep1-0"
    assert cand.metadata["referenced_files"] == ["app/routes/books.py"]
    assert cand.metadata["episode_type"] == "decision"
    model, messages = fake.seen[0]
    assert model == "m" and "rejected" in messages[1]["content"]  # per-type guidance


async def test_openai_style_clients_sync_and_async() -> None:
    def make(reply: str, is_async: bool) -> Any:
        resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

        async def acreate(**kw: Any) -> Any:
            return resp

        create = acreate if is_async else (lambda **kw: resp)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    for is_async in (False, True):
        cands = await llm_extractor(make(REPLY, is_async), "m")(EPISODE)
        assert len(cands) == 1


async def test_bad_reply_falls_back_to_default() -> None:
    cands = await llm_extractor(Fake("no json here"), "m")(EPISODE)
    assert len(cands) == 1 and cands[0].text.startswith("Cursor pagination is stable")


def test_parse_entries_errors() -> None:
    with pytest.raises(ValueError):
        parse_entries('{"items": []}')
    assert parse_entries('{"entries": []}') == []


async def test_http_client() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/chat/completions")
        assert req.headers["authorization"] == "Bearer k"
        body = json.loads(req.content)
        assert body["model"] == "m" and body["temperature"] == 0.0
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    client = OpenAICompatibleClient("https://example.test/api/v1/", "k",
                                    transport=httpx.MockTransport(handler))
    assert await client.complete("m", [{"role": "user", "content": "x"}]) == "hi"


def test_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        openrouter_extractor_from_env()
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("EXTRACTOR_MODEL", "some/model")
    assert callable(openrouter_extractor_from_env())
