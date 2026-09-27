"""Built-in deterministic code checks, registered on import."""

from __future__ import annotations

from typing import Any

from memworthy.checks.dates import classify_timing
from memworthy.checks.registry import register_check
from memworthy.checks.secrets import secret_scan
from memworthy.models import Candidate

VERIFIED_OUTCOMES = ("tests_passed", "build_passed", "committed", "user_confirmed")


def source_is_user(candidate: Candidate, args: dict[str, Any]) -> bool:
    """True when the candidate's source role is allowed (default: user only)."""
    allowed = args.get("allow_roles") or ["user"]
    return candidate.source.role in allowed


def date_parse(candidate: Candidate, args: dict[str, Any]) -> str:
    """Timing of the candidate: past, present, future, bounded or none."""
    now = args.get("now") or candidate.metadata.get("timestamp")
    return classify_timing(candidate.text, now)


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _matches(ref: str, read: list[str]) -> bool:
    r = _norm(ref)
    return any(_norm(p) == r or _norm(p).endswith("/" + r) or r.endswith("/" + _norm(p))
               for p in read)


def file_was_read(candidate: Candidate, args: dict[str, Any]) -> bool:
    """True when enough referenced files were read in the session.

    With no referenced files there is nothing to ground the entry in, so it returns False.
    """
    refs = [str(p) for p in candidate.metadata.get("referenced_files") or []]
    read = [str(p) for p in candidate.metadata.get("files_read") or []]
    if not refs:
        return False
    fraction = sum(_matches(r, read) for r in refs) / len(refs)
    return fraction >= float(args.get("min_fraction", 1.0))


def outcome_verified(candidate: Candidate, args: dict[str, Any]) -> bool:
    """True when the episode outcome is verified (tests, build, commit or user sign-off)."""
    accept = args.get("accept") or list(VERIFIED_OUTCOMES)
    return candidate.metadata.get("outcome") in accept


register_check("source_is_user", source_is_user)
register_check("secret_scan", secret_scan)
register_check("date_parse", date_parse)
register_check("file_was_read", file_was_read)
register_check("outcome_verified", outcome_verified)
