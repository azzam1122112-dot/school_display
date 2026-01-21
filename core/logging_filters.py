from __future__ import annotations

import logging


class SnapshotRequestNoiseFilter(logging.Filter):
    """Suppress noisy django.request warnings for snapshot polling.

    We intentionally keep snapshot endpoints public-but-device-bound.
    External scanners/bots may hit these endpoints without required headers,
    producing expected 403/429 responses that would otherwise clutter logs.
    """

    SNAPSHOT_PREFIX = "/api/display/snapshot/"
    _NOISY_PREFIXES = (
        "Forbidden:",
        "Too Many Requests:",
    )

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if record.name != "django.request":
                return True

            msg = record.getMessage() or ""
            if not msg.startswith(self._NOISY_PREFIXES):
                return True

            # Typical formats:
            # - "Forbidden: /api/display/snapshot/<token>/"
            # - "Too Many Requests: /api/display/snapshot/<token>/"
            if self.SNAPSHOT_PREFIX in msg:
                return False

            return True
        except Exception:
            # Never break logging.
            return True
