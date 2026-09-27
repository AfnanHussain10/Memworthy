"""Scrub Claude Code or Codex session JSONL files for use as test fixtures.

Keeps every record's structure (keys, types, order) so parsers are tested against the real
format, while removing private content:

- secrets (Memworthy's own ``secret_scan`` patterns), emails, IP addresses, phone numbers
- the home directory, user name and given ``--term`` words (for example project names)
- hostnames of URLs outside a small allowlist
- model thinking/reasoning text, encrypted content, system instructions, file snapshots
- long strings are truncated to their head and tail

Usage::

    python scripts/scrub_sessions.py OUT_DIR FILE... --term acme=sample --term alice=dev

Always review the output by hand before committing it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from memworthy.checks.secrets import redact_text

MAX_STRING = 1200
KEEP_HEAD, KEEP_TAIL = 700, 300
URL_ALLOW = {"github.com", "pypi.org", "localhost", "127.0.0.1", "example.com", "docs.python.org",
             "api.anthropic.com", "openai.com"}
DROP_TEXT_KEYS = {"thinking", "signature", "encrypted_content", "base_instructions",
                  "snapshot", "backup", "originalFile", "structuredPatch", "rendered",
                  "user_instructions", "developer_instructions", "hookAdditionalContext",
                  "attachment", "dynamic_tools", "mcpMeta"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
PHONE = re.compile(r"\+\d[\d\s().-]{8,}\d")
URL = re.compile(r"https?://([A-Za-z0-9.-]+)")


class Scrubber:
    def __init__(self, home: str, terms: dict[str, str]) -> None:
        self.home = home
        user = Path(home).name
        pairs = {home: "/home/dev", user: "dev", user.capitalize(): "Dev"}
        pairs.update(terms)
        # Longest first so "acme-backend" is replaced before "acme".
        self.terms = sorted(pairs.items(), key=lambda kv: -len(kv[0]))

    def text(self, s: str) -> str:
        s = redact_text(s)[0]
        for old, new in self.terms:
            s = re.sub(re.escape(old), new, s, flags=re.IGNORECASE)
        s = EMAIL.sub("dev@example.com", s)
        s = URL.sub(lambda m: m.group(0) if m.group(1) in URL_ALLOW or
                    m.group(1).endswith(".github.com") else
                    m.group(0).replace(m.group(1), "example.com"), s)
        s = IPV4.sub(lambda m: m.group(0) if m.group(0).startswith("127.") else "10.0.0.1", s)
        s = PHONE.sub("+10000000000", s)
        if len(s) > MAX_STRING:
            s = f"{s[:KEEP_HEAD]}\n[... {len(s) - KEEP_HEAD - KEEP_TAIL} chars truncated ...]\n" \
                f"{s[-KEEP_TAIL:]}"
        return s

    def value(self, v: Any, key: str = "") -> Any:
        if key in DROP_TEXT_KEYS:
            if isinstance(v, str):
                return "[removed]" if v else v
            if isinstance(v, (dict, list)):
                return type(v)()
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x, key) for x in v]
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            for k, x in v.items():
                if key == "content" and k == "text" and v.get("type") == "thinking":
                    out[k] = "[removed]"
                    continue
                out[self.text(k) if k.startswith("/") else k] = self.value(x, k)
            if v.get("type") == "reasoning":
                out["summary"] = []
                out["content"] = None
            return out
        return v


def scrub_file(src: Path, dest: Path, scrubber: Scrubber) -> int:
    lines = []
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        if record.get("type") in ("world_state",):
            record["payload"] = {}
        lines.append(json.dumps(scrubber.value(record), ensure_ascii=False))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--term", action="append", default=[], help="old=new replacement")
    ap.add_argument("--home", default=os.path.expanduser("~"))
    args = ap.parse_args()
    terms = dict(t.split("=", 1) for t in args.term)
    scrubber = Scrubber(args.home, terms)
    for f in args.files:
        src = Path(f)
        dest = Path(args.out_dir) / src.name
        n = scrub_file(src, dest, scrubber)
        print(f"{src.name}: {n} records -> {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
