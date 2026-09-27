"""Vendored secret patterns and redaction. No network calls, no dependencies."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from memworthy.models import Candidate

# Order matters: more specific patterns come before generic ones.
PATTERNS: dict[str, str] = {
    "private_key": (r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
                    r"(?:[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----)?"),
    "anthropic": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "openrouter": r"\bsk-or-v1-[A-Za-z0-9]{32,}",
    "openai": r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
    "typesafe": r"\bapikey_[A-Za-z0-9_]{32,}",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "github": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})",
    "stripe": r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}",
    "slack": r"\bxox[abposr]-[A-Za-z0-9-]{10,}|https://hooks\.slack\.com/services/[A-Za-z0-9/]+",
    "google": r"\bAIza[0-9A-Za-z_-]{35}",
    "jwt": r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
    "connection_string": r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:[^\s@/]+@[^\s'\"]+",
}
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:key|secret|token|password|passwd|pwd|credential)[A-Za-z0-9_]*)"
    r"(\s*[=:]\s*[\"']?)([^\s\"']{8,})"
)
_COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}


def shannon_entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _patterns(args: dict[str, Any]) -> dict[str, re.Pattern[str]]:
    extra = args.get("extra_patterns") or {}
    out = dict(_COMPILED)
    for name, pattern in extra.items():
        out[str(name)] = re.compile(str(pattern))
    return out


def redact_text(text: str, args: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """Replace every secret with ``[REDACTED:<kind>]``; return the text and kinds found."""
    args = args or {}
    threshold = float(args.get("entropy_threshold", 4.0))
    kinds: list[str] = []
    for kind, pattern in _patterns(args).items():
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            kinds.append(kind)

    def repl(m: re.Match[str]) -> str:
        value = m.group(3)
        if value.startswith("[REDACTED:") or shannon_entropy(value) < threshold:
            return m.group(0)
        kinds.append("assignment")
        return f"{m.group(1)}{m.group(2)}[REDACTED:assignment]"

    text = _ASSIGNMENT.sub(repl, text)
    return text, sorted(set(kinds))


def find_secrets(text: str, args: dict[str, Any] | None = None) -> list[str]:
    """Kinds of secrets found in ``text``."""
    return redact_text(text, args)[1]


def secret_scan(candidate: Candidate, args: dict[str, Any]) -> bool:
    """True when the candidate's text, context or source text contains a secret."""
    return any(
        find_secrets(t, args) for t in (candidate.text, candidate.context, candidate.source.text)
    )


def redact_candidate(candidate: Candidate, args: dict[str, Any]) -> tuple[Candidate, str]:
    """Redact text, context and source text; return the new candidate and redacted text."""
    text = redact_text(candidate.text, args)[0]
    context = redact_text(candidate.context, args)[0]
    source_text = redact_text(candidate.source.text, args)[0]
    source = candidate.source.model_copy(update={"text": source_text})
    new = candidate.model_copy(update={"text": text, "context": context, "source": source})
    return new, text
