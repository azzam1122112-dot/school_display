from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import redis


SNAPSHOT_QUEUE_METRIC_KEYS = [
    "metrics:snapshot_queue:coalesced",
    "metrics:snapshot_queue:latest_revision_replaced",
    "metrics:snapshot_queue:queue_skipped_outdated",
    "metrics:snapshot_queue:outdated_job_dropped",
    "metrics:snapshot_queue:enqueued",
    "metrics:snapshot_queue:dequeued",
    "metrics:snapshot_queue:materialized",
]


def _queue_redis():
    redis_url = str(getattr(settings, "REDIS_CHANNELS_URL", "") or "").strip()
    if not redis_url:
        raise CommandError("REDIS_CHANNELS_URL is not configured.")
    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=True,
        health_check_interval=30,
    )


class Command(BaseCommand):
    help = "Reset snapshot queue diagnostic metrics stored in the queue Redis."

    def handle(self, *args, **options):
        conn = _queue_redis()
        try:
            if SNAPSHOT_QUEUE_METRIC_KEYS:
                conn.delete(*SNAPSHOT_QUEUE_METRIC_KEYS)
        except Exception as exc:
            raise CommandError(f"Failed to reset snapshot queue metrics: {exc.__class__.__name__}") from exc

        self.stdout.write("Snapshot queue metrics reset successfully.")
