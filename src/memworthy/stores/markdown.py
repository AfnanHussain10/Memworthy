"""Markdown folder sink: one file per memory with YAML frontmatter, Obsidian-compatible.

Layout: ``<root>/<type>/<slug>.md`` and ``<root>/_archive/<type>/<slug>.md``. Nothing is ever
deleted: superseded entries move to the archive with ``superseded_by`` in their frontmatter.
"""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from memworthy.models import Memory, SourceRef
from memworthy.stores.local import LocalStore

ARCHIVE = "_archive"
FRONTMATTER_KEYS = ("files", "commit", "dependency_versions", "policy", "policy_version",
                    "confidence")
SOURCE_TEXT_CHARS = 300


class _NoAliasDumper(yaml.SafeDumper):
    """Safe dumper that writes repeated values in full instead of YAML anchors."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def slugify(text: str, words: int = 8) -> str:
    """Lowercase slug from the first ``words`` words."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())[:words]
    return "-".join(tokens) or "entry"


def to_markdown(memory: Memory) -> str:
    """Render a memory as frontmatter plus body."""
    meta = dict(memory.metadata)
    front: dict[str, Any] = {
        "id": memory.id, "type": memory.type, "subject": memory.subject,
        "labels": list(memory.labels),
        "created_at": memory.created_at.isoformat(), "updated_at": memory.updated_at.isoformat(),
        "sources": [{"role": s.role, "session_id": s.session_id, "message_id": s.message_id,
                     "text": s.text[:SOURCE_TEXT_CHARS]} for s in memory.sources],
    }
    for key in FRONTMATTER_KEYS:
        if key in meta:
            front[key] = meta.pop(key)
    if meta:
        front["metadata"] = meta
    body = yaml.dump(front, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True,
                     width=100)
    return f"---\n{body}---\n\n{memory.text.strip()}\n"


def from_markdown(text: str) -> Memory:
    """Parse a file written by :func:`to_markdown`."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    _, front_text, body = text.split("---\n", 2)
    front = yaml.safe_load(front_text) or {}
    meta = dict(front.get("metadata") or {})
    for key in FRONTMATTER_KEYS:
        if key in front:
            meta[key] = front[key]
    return Memory(
        id=str(front["id"]), text=body.strip(), type=str(front["type"]),
        subject=str(front.get("subject", "user")),
        created_at=datetime.fromisoformat(str(front["created_at"])),
        updated_at=datetime.fromisoformat(str(front["updated_at"])),
        sources=[SourceRef(**s) for s in front.get("sources") or []],
        labels=[str(x) for x in front.get("labels") or []], metadata=meta)


class MarkdownStore(LocalStore):
    """Writes each memory to its own Markdown file; reloads existing files on start."""

    def __init__(self, root: str | Path) -> None:
        """Open (or create) a knowledge base folder."""
        super().__init__()
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths: dict[str, Path] = {}
        for path in sorted(self.root.rglob("*.md")):
            try:
                mem = from_markdown(path.read_text(encoding="utf-8"))
            except (ValueError, KeyError, yaml.YAMLError):
                continue
            rel = path.relative_to(self.root)
            if rel.parts[0] == ARCHIVE:
                self.archive[mem.id] = mem
            else:
                self.memories[mem.id] = mem
                self.paths[mem.id] = path

    def _path_for(self, memory: Memory, base: Path) -> Path:
        folder = base / slugify(memory.type, 3)
        path = folder / f"{slugify(memory.text)}.md"
        if path.exists() and self.paths.get(memory.id) != path:
            path = folder / f"{slugify(memory.text)}-{memory.id[:6]}.md"
        return path

    def _save(self, memory: Memory) -> None:
        path = self.paths.get(memory.id) or self._path_for(memory, self.root)
        _atomic_write(path, to_markdown(memory))
        self.paths[memory.id] = path

    def _retire(self, memory: Memory) -> None:
        old = self.paths.pop(memory.id, None)
        dest = self._path_for(memory, self.root / ARCHIVE)
        _atomic_write(dest, to_markdown(memory))
        if old is not None and old.exists():
            old.unlink()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
