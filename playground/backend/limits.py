"""Live-mode guards: per-IP and global rate limits and a daily spend cap (in memory)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

JEV_PRICE_PER_TOKEN = 0.042 / 1_000_000  # USD per input token; output tokens are free


@dataclass
class LiveLimits:
    """Sliding-window limits on live judge calls plus a per-UTC-day spend cap."""

    per_ip_per_hour: int = 40
    global_per_hour: int = 600
    daily_cap_usd: float = 0.50
    _ip: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _all: deque[float] = field(default_factory=deque)
    _day: str = ""
    spent_usd: float = 0.0

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] > 3600:
            q.popleft()

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self._day:
            self._day, self.spent_usd = today, 0.0

    def check(self, ip: str, now: float | None = None) -> str | None:
        """None if a live call is allowed, else a friendly reason."""
        now = time.time() if now is None else now
        self._roll_day()
        if self.spent_usd >= self.daily_cap_usd:
            return "Today's live-mode budget is used up. Recorded demos still work."
        q = self._ip[ip]
        self._prune(q, now)
        self._prune(self._all, now)
        if len(q) >= self.per_ip_per_hour:
            return "You've reached the live-mode limit for this hour. Recorded demos still work."
        if len(self._all) >= self.global_per_hour:
            return "Live mode is busy right now. Recorded demos still work."
        return None

    def record(self, ip: str, input_tokens: int, now: float | None = None) -> None:
        """Count one live call and its cost."""
        now = time.time() if now is None else now
        self._roll_day()
        self._ip[ip].append(now)
        self._all.append(now)
        self.spent_usd += input_tokens * JEV_PRICE_PER_TOKEN
