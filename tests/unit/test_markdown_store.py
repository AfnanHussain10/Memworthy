from __future__ import annotations

from pathlib import Path

import pytest

from memgate.models import Candidate, Decision, Patch, SignalValue
from memgate.stores.markdown import MarkdownStore, from_markdown, slugify, to_markdown


def decision(action: str, text: str, target=None, patch=None, **kw):  # type: ignore[no-untyped-def]
    cand = Candidate.from_text(text, subject="proj",
                               metadata={"files": ["a.py"], "commit": "abc123"})
    return Decision(candidate=cand, action=action, type="decision",
                    signals={"type": SignalValue(name="type", kind="choice", value="decision",
                                                 confidence=0.9)},
                    rule="r", target=target, patch=patch, policy="dev-sessions",
                    policy_version="1.1", judge="mock", latency_ms=1, **kw)


def test_slugify() -> None:
    assert slugify("Chose Postgres over Mongo, because: joins & transactions matter a lot") \
        == "chose-postgres-over-mongo-because-joins-transactions-matter"
    assert slugify("!!!") == "entry"


async def test_store_reload_update_supersede_restore(tmp_path: Path) -> None:
    root = tmp_path / "kb"
    s = MarkdownStore(root)
    m = await s.apply(decision("store", "Use Redis for the page cache"))
    assert m is not None
    path = root / "decision" / "use-redis-for-the-page-cache.md"
    text = path.read_text()
    assert text.startswith("---\n") and "policy_version: '1.1'" in text
    assert "files:\n- a.py" in text and "commit: abc123" in text and "confidence: 0.9" in text
    assert "&id" not in text  # no YAML anchors
    # A second entry with the same slug gets an id suffix.
    m2 = await s.apply(decision("store", "Use Redis for the page cache"))
    assert m2 is not None and (root / "decision" / f"use-redis-for-the-page-cache-{m2.id[:6]}.md"
                               ).exists()

    reopened = MarkdownStore(root)
    assert set(reopened.memories) == {m.id, m2.id}
    assert reopened.memories[m.id] == m

    u = await reopened.apply(decision("update", "Use Memcached for the page cache", target=m,
                                      patch=Patch(target_id=m.id, old_text=m.text,
                                                  new_text="Use Memcached for the page cache")))
    assert u is not None and path.exists()  # updates keep their file
    assert "previous_text: Use Redis for the page cache" in path.read_text()

    back = await reopened.apply(decision("supersede", "Actually keep Redis", target=u,
                                         patch=Patch(target_id=u.id, old_text=u.text,
                                                     new_text="Use Redis for the page cache",
                                                     restore=True)))
    assert back is not None and back.text == "Use Redis for the page cache"
    # the archived version leaves; the restored text takes the freed filename again
    assert from_markdown(path.read_text()).id == back.id
    archived = list((root / "_archive").rglob("*.md"))
    assert len(archived) == 1
    arch = from_markdown(archived[0].read_text())
    assert arch.metadata["superseded_by"] == back.id and arch.text.startswith("Use Memcached")
    third = MarkdownStore(root)
    assert u.id in third.archive and back.id in third.memories
    assert [x.id for x in await third.similar(Candidate.from_text("redis cache", subject="proj"),
                                              5)][:1] in ([back.id], [m2.id])


async def test_merge_and_noop(tmp_path: Path) -> None:
    s = MarkdownStore(tmp_path)
    m = await s.apply(decision("store", "Deploy with Docker"))
    assert m is not None
    merged = await s.apply(decision("merge", "Deploy with docker again", target=m))
    assert merged is not None and len(merged.sources) == 2
    assert await s.apply(decision("reject", "x")) is None
    assert len(list(tmp_path.rglob("*.md"))) == 1


def test_bad_files_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("# my own notes\n")
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "broken.md").write_text("---\nid: 1\n---\nno type\n")
    assert MarkdownStore(tmp_path).memories == {}
    with pytest.raises(ValueError):
        from_markdown("no frontmatter")


def test_roundtrip_without_extra_metadata() -> None:
    d = decision("store", "x")
    from memgate.stores.base import new_memory

    mem = new_memory(d).model_copy(update={"metadata": {}})
    assert from_markdown(to_markdown(mem)) == mem
