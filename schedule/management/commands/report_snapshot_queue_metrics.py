from __future__ import annotations

import logging

from django.core.cache import cache
from django.core.cache import caches
from django.core.management.base import BaseCommand, CommandError


logger = logging.getLogger(__name__)

SNAPSHOT_QUEUE_METRIC_KEYS = [
    "metrics:snapshot_queue:coalesced",
    "metrics:snapshot_queue:latest_revision_replaced",
    "metrics:snapshot_queue:queue_skipped_outdated",
    "metrics:snapshot_queue:outdated_job_dropped",
    "metrics:snapshot_queue:enqueued",
    "metrics:snapshot_queue:dequeued",
    "metrics:snapshot_queue:materialized",
]


def _cache_backend_name() -> str:
    try:
        backend = caches["default"]
        return f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    except Exception:
        return f"{cache.__class__.__module__}.{cache.__class__.__name__}"


def _metric_name(key: str) -> str:
    return key.rsplit(":", 1)[-1]


def _to_int(value: object) -> int:
    if value is None:
        return 0
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return int(value)
    except Exception:
        return 0


def _percent(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int(round((float(numerator) / float(denominator)) * 100))


class Command(BaseCommand):
    help = "Report snapshot queue diagnostic metrics from the Django cache backend."

    def handle(self, *args, **options):
        try:
            raw_values = cache.get_many(SNAPSHOT_QUEUE_METRIC_KEYS)
        except Exception as exc:
            raise CommandError(f"Failed to read snapshot queue metrics: {exc.__class__.__name__}") from exc

        metrics = {
            _metric_name(key): _to_int(raw_values.get(key))
            for key in SNAPSHOT_QUEUE_METRIC_KEYS
        }

        enqueued = int(metrics.get("enqueued", 0) or 0)
        materialized = int(metrics.get("materialized", 0) or 0)
        coalesced = int(metrics.get("coalesced", 0) or 0)
        latest_revision_replaced = int(metrics.get("latest_revision_replaced", 0) or 0)
        queue_skipped_outdated = int(metrics.get("queue_skipped_outdated", 0) or 0)
        outdated_job_dropped = int(metrics.get("outdated_job_dropped", 0) or 0)

        efficiency = _percent(materialized, enqueued)
        coalescing_ratio = _percent(coalesced + latest_revision_replaced, enqueued)
        drop_ratio = _percent(outdated_job_dropped + queue_skipped_outdated, enqueued)

        self.stdout.write("Snapshot Queue Metrics")
        self.stdout.write("----------------------")
        self.stdout.write(f"source: django cache default ({_cache_backend_name()})")
        self.stdout.write("")
        self.stdout.write(f"enqueued: {enqueued}")
        self.stdout.write(f"dequeued: {metrics.get('dequeued', 0)}")
        self.stdout.write(f"materialized: {materialized}")
        self.stdout.write("")
        self.stdout.write(f"coalesced: {coalesced}")
        self.stdout.write(f"latest_revision_replaced: {latest_revision_replaced}")
        self.stdout.write(f"queue_skipped_outdated: {queue_skipped_outdated}")
        self.stdout.write(f"outdated_job_dropped: {outdated_job_dropped}")
        self.stdout.write("")
        self.stdout.write("efficiency:")
        self.stdout.write(f"- materialized / enqueued = {efficiency}%")
        self.stdout.write(f"- coalescing impact = {coalescing_ratio}%")
        self.stdout.write(f"- drop impact = {drop_ratio}%")

        logger.info("snapshot_queue_metrics_report generated")
