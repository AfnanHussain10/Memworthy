"""Small rule-based parser for English time expressions.

Classifies text as ``past``, ``present``, ``future``, ``bounded`` (has an end date) or
``none``. It is deliberately limited and returns ``none`` when unsure.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

Timing = Literal["past", "present", "future", "bounded", "none"]

_NUM = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|few|couple of|several)"
_UNIT = r"(?:minutes?|hours?|days?|nights?|weeks?|weekends?|months?|years?)"
_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_MONTH = (r"(?:january|february|march|april|may|june|july|august|september|october|"
          r"november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)")

BOUNDED = [
    r"\buntil\b", r"\btill\b", r"\buntil the end of\b",
    r"\bthis (?:week|weekend|month|morning|afternoon|evening|summer|winter|spring|fall)\b",
    r"\b(?:today|tonight)\b", r"\bfor now\b", r"\bthrough (?:the )?(?:end|" + _WEEKDAY + r")\b",
    rf"\bfor (?:the )?(?:next|coming) (?:{_NUM} )?{_UNIT}\b",
    r"\b(?:temporarily|at the moment only)\b",
]
# Plain durations ("for two weeks") bound a state only when it is not a present-perfect
# span reaching up to now ("I've been a designer for six years").
DURATION = [
    rf"\bfor (?:the )?{_NUM} {_UNIT}\b",
    r"\bfor (?:a|the) (?:week|weekend|month|day|while)\b",
]
PERFECT = r"\b(?:have|has|'ve|'s) (?:been|lived|had|worked|owned|known|used|played|studied)\b"
FUTURE = [
    r"\btomorrow\b", rf"\bnext {_UNIT}\b", rf"\bnext {_WEEKDAY}\b", r"\bnext (?:summer|winter|"
    r"spring|fall|autumn|year)\b", rf"\bin {_NUM} {_UNIT}\b", r"\bsoon\b", r"\blater (?:today|"
    r"this (?:week|month|year))\b", rf"\bthis (?:coming )?{_WEEKDAY}\b", r"\bupcoming\b",
    r"\bday after tomorrow\b", r"\bfrom next\b",
]
PAST = [
    r"\byesterday\b", rf"\blast (?:{_UNIT}|{_WEEKDAY}|summer|winter|spring|fall|autumn|night)\b",
    rf"\b{_NUM} {_UNIT} ago\b", r"\brecently\b", r"\bearlier (?:today|this (?:week|month|year))\b",
    r"\bpreviously\b", r"\bback in\b", r"\bused to\b",
]
PRESENT = [
    r"\bsince\b", r"\b(?:currently|nowadays|these days|right now|at the moment|at present)\b",
    r"\bnow\b",
]
_YEAR = re.compile(r"\b(?:in|by|since|from|during|until|of)?\s*((?:19|20)\d{2})\b")
_ISO = re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b")
_MONTH_DATE = re.compile(
    rf"\b({_MONTH})\.? (\d{{1,2}})(?:st|nd|rd|th)?(?:,? ((?:19|20)\d{{2}}))?\b"
)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def parse_now(value: str | datetime | None) -> datetime:
    """Parse an ISO timestamp (or None for now) into an aware datetime."""
    if isinstance(value, datetime):
        dt = value
    elif value:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _absolute(text: str, now: datetime) -> Timing | None:
    dates: list[datetime] = []
    for m in _ISO.finditer(text):
        try:
            dates.append(datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc))
        except ValueError:
            continue
    for m in _MONTH_DATE.finditer(text):
        month = _MONTHS.index(m[1][:3]) + 1
        year = int(m[3]) if m[3] else now.year
        try:
            dates.append(datetime(year, month, int(m[2]), tzinfo=timezone.utc))
        except ValueError:
            continue
    if dates:
        d = dates[0]
        if d.date() > now.date():
            return "future"
        if d.date() < now.date():
            return "past"
        return "present"
    ym = _YEAR.search(text)
    if ym:
        year = int(ym[1])
        if re.search(r"\bsince\s+(?:19|20)\d{2}\b", text):
            return "present"
        if year > now.year:
            return "future"
        if year < now.year:
            return "past"
    return None


def classify_timing(text: str, now: str | datetime | None = None) -> Timing:
    """Classify the time reference in ``text`` relative to ``now``."""
    t = " ".join(text.lower().split())
    if _any(BOUNDED, t):
        return "bounded"
    if _any(DURATION, t):
        return "present" if re.search(PERFECT, t) else "bounded"
    if _any(FUTURE, t):
        return "future"
    if _any(PAST, t):
        return "past"
    if _any(PRESENT, t):
        return "present"
    return _absolute(t, parse_now(now)) or "none"
