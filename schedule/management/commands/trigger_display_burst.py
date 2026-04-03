from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from schedule.cache_utils import (
    bump_schedule_revision_for_school_id,
    invalidate_display_snapshot_cache_for_school_id,
)
from schedule.models import SchoolSettings
from schedule.snapshot_materializer import enqueue_snapshot_build


class Command(BaseCommand):
    help = "Trigger repeated display invalidations for load testing."

    def add_arguments(self, parser):
        parser.add_argument("--school-id", type=int, default=0, help="Target school_id. If omitted and only one school exists, it will be used.")
        parser.add_argument("--count", type=int, default=1, help="Number of invalidations to trigger.")
        parser.add_argument("--interval-ms", type=int, default=250, help="Delay between invalidations.")

    def handle(self, *args, **options):
        school_id = int(options.get("school_id") or 0)
        count = max(1, int(options.get("count") or 1))
        interval_ms = max(0, int(options.get("interval_ms") or 0))

        if not school_id:
            total = SchoolSettings.objects.count()
            if total != 1:
                raise CommandError("--school-id is required unless exactly one SchoolSettings row exists.")
            school_id = int(SchoolSettings.objects.values_list("school_id", flat=True).first() or 0)

        if not school_id:
            raise CommandError("No valid school_id found.")

        try:
            from schedule.signals import _broadcast_invalidate_ws
        except Exception as exc:
            raise CommandError(f"Unable to import WS broadcast helper: {exc}") from exc

        for idx in range(count):
            new_rev = bump_schedule_revision_for_school_id(school_id) or 0
            invalidate_display_snapshot_cache_for_school_id(school_id)
            enqueue_snapshot_build(
                school_id=school_id,
                rev=int(new_rev),
                day_key=timezone.localdate().isoformat(),
                reason="load_test_burst",
            )
            _broadcast_invalidate_ws(school_id, int(new_rev))
            self.stdout.write(
                f"burst_event index={idx + 1} school_id={school_id} revision={int(new_rev)}"
            )
            if idx + 1 < count and interval_ms > 0:
                time.sleep(interval_ms / 1000.0)
