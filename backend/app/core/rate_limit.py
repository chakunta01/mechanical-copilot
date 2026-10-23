"""Rate limiting middleware: fixed-window counter keyed by client + IP.

Production note: for multi-replica deployments, move the counter to Redis.
The interface (`RateLimiter.check`) is kept storage-agnostic for that swap.
"""

from __future__ import annotations

import time
from collections import defaultdict

from app.core.config import settings
from app.core.errors import RateLimited


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self._hits[key]
        # Drop entries older than 60s.
        self._hits[key] = [t for t in window if now - t < 60.0]
        if len(self._hits[key]) >= self.per_minute:
            raise RateLimited("Rate limit exceeded. Retry shortly.")
        self._hits[key].append(now)


limiter = RateLimiter(settings.rate_limit_per_min)
