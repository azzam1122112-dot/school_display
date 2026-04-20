from __future__ import annotations

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError


SNAPSHOT_QUEUE_METRIC_KEYS = [
    "metrics:snapshot_queue:coalesced",
    "metrics:snapshot_queue:deduped",
    "metrics:snapshot_queue:debounced",
    "metrics:snapshot_queue:latest_revision_replaced",
    "metrics:snapshot_queue:queue_skipped_outdated",
    "metrics:snapshot_queue:outdated_job_dropped",
    "metrics:snapshot_queue:enqueued",
    "metrics:snapshot_queue:dequeued",
    "metrics:snapshot_queue:materialized",
]


class Command(BaseCommand):
    help = "Reset snapshot queue diagnostic metrics stored in the Django cache backend."

    def handle(self, *args, **options):
        try:
            cache.delete_many(SNAPSHOT_QUEUE_METRIC_KEYS)
        except Exception as exc:
            raise CommandError(f"Failed to reset snapshot queue metrics: {exc.__class__.__name__}") from exc

        self.stdout.write("Snapshot queue metrics reset successfully.")
