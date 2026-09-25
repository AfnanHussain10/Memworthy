"""Decision ledgers: the audit trail, the replay input and the review queue."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from memgate.models import Decision

log = logging.getLogger("memgate.ledger")
HEADER = {"memgate_ledger": 1}


class LedgerError(Exception):
    """A ledger file is unreadable."""


@runtime_checkable
class Ledger(Protocol):
    """Records every decision."""

    def record(self, decision: Decision) -> None:
        """Append one decision."""
        ...

    def read(self) -> Iterator[Decision]:
        """Yield recorded decisions in order."""
        ...


class JsonlLedger:
    """One JSON line per decision, after a ``{"memgate_ledger": 1}`` header line."""

    def __init__(self, path: str | Path | None = None) -> None:
        """Use ``path``, else MEMGATE_LEDGER, else ``memgate.ledger.jsonl``."""
        self.path = Path(path or os.environ.get("MEMGATE_LEDGER") or "memgate.ledger.jsonl")

    def record(self, decision: Decision) -> None:
        """Append a decision, writing the header first if the file is new or empty."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        line = json.dumps(decision.model_dump(mode="json"), ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as fh:
            if new:
                fh.write(json.dumps(HEADER) + "\n")
            fh.write(line + "\n")

    def read(self) -> Iterator[Decision]:
        """Yield decisions; raise LedgerError on a bad header or line."""
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for n, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except ValueError as exc:
                    raise LedgerError(f"{self.path}:{n}: invalid JSON ({exc})") from None
                if n == 1:
                    if data != HEADER:
                        raise LedgerError(f"{self.path}: missing memgate_ledger header")
                    continue
                yield Decision.model_validate(data)


class MemoryLedger:
    """In-memory ledger for tests and the playground."""

    def __init__(self) -> None:
        """Start empty."""
        self.decisions: list[Decision] = []

    def record(self, decision: Decision) -> None:
        """Append a decision."""
        self.decisions.append(decision)

    def read(self) -> Iterator[Decision]:
        """Yield decisions in order."""
        yield from list(self.decisions)

    def to_jsonl(self) -> str:
        """Serialize in the same format JsonlLedger writes."""
        lines = [json.dumps(HEADER)]
        lines += [json.dumps(d.model_dump(mode="json"), ensure_ascii=False)
                  for d in self.decisions]
        return "\n".join(lines) + "\n"
