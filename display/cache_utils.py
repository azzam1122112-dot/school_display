from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache


@dataclass(frozen=True)
class CacheKeys:
    """Centralized cache key builder for display-related caching."""

    def _token_hash(self, token: str) -> str:
        return hashlib.sha256((token or "").encode("utf-8")).hexdigest()

    # token -> school_id cache (short)
    def token_school(self, token: str) -> str:
        # Avoid storing raw tokens in Redis keys.
        return f"display:token_school:{self._token_hash(token)}"

    # rev per school (small/fast)
    def school_rev(self, school_id: int) -> str:
        return f"display:school:{int(school_id)}:rev"

    # snapshot per school+rev+day
    def snapshot(self, school_id: int, rev: int, day_key: str) -> str:
        return f"display:snap:v5:school:{int(school_id)}:rev:{int(rev)}:day:{day_key}"

    # short-lived snapshot used only during time-based transitions (countdown==0)
    def snapshot_transition(self, school_id: int, rev: int, day_key: str) -> str:
        return f"display:snap:v5:school:{int(school_id)}:rev:{int(rev)}:day:{day_key}:transition"

    # stale snapshot per school+day (rev-agnostic)
    def school_snapshot_stale(self, school_id: int, day_key: str) -> str:
        return f"display:school_snapshot:stale:school:{int(school_id)}:day:{day_key}"

    # lock key
    def snapshot_lock(self, school_id: int, rev: int, day_key: str) -> str:
        return f"display:lock:snap:school:{int(school_id)}:rev:{int(rev)}:day:{day_key}"


keys = CacheKeys()


def cache_add_lock(lock_key: str, ttl: int = 10) -> bool:
    """Acquire a Redis-backed lock.

    cache.add is atomic in Redis: succeeds only if key does not exist.
    """
    return bool(cache.add(lock_key, "1", timeout=int(ttl)))


def cache_wait_for(key: str, timeout_s: float = 0.6, step_s: float = 0.05) -> Any:
    """Wait briefly for a cache value to appear to avoid repeated rebuilds."""
    t0 = time.time()
    while (time.time() - t0) < float(timeout_s):
        val = cache.get(key)
        if val is not None:
            return val
        time.sleep(float(step_s))
    return None
