from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from schedule.snapshot_materializer import (
    complete_snapshot_job,
    dequeue_snapshot_build,
    materialize_snapshot_for_school,
    snapshot_queue_available,
    touch_snapshot_worker_heartbeat,
)


class Command(BaseCommand):
    help = "Materialize display snapshots from the Redis-backed build queue."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one queued job, then exit.")
        parser.add_argument("--poll-timeout", type=int, default=5, help="BLPOP timeout in seconds.")
        parser.add_argument("--idle-sleep", type=float, default=0.5, help="Sleep duration after empty polls.")

    def handle(self, *args, **options):
        once = bool(options.get("once"))
        poll_timeout = max(0, int(options.get("poll_timeout") or 0))
        idle_sleep = max(0.1, float(options.get("idle_sleep") or 0.5))
        worker_id = f"snapshot-worker:{int(time.time())}"

        if not snapshot_queue_available():
            self.stdout.write("snapshot_queue_available=False")
            if once:
                return

        self.stdout.write(f"snapshot_worker_started id={worker_id} poll_timeout={poll_timeout}")
        while True:
            touch_snapshot_worker_heartbeat(worker_id=worker_id)
            job = dequeue_snapshot_build(block_timeout=poll_timeout)
            if not job:
                if once:
                    self.stdout.write("snapshot_worker_idle")
                    return
                time.sleep(idle_sleep)
                continue

            try:
                school_id = int(job.get("school_id") or 0)
                rev = int(job.get("rev") or 0)
                day_key = str(job.get("day_key") or "")
                if job.get("_skip_complete"):
                    self.stdout.write(
                        f"snapshot_worker_job school_id={school_id} requested_rev={rev} day_key={day_key} queue_wait_ms=0 process_ms=0 ok=1 result={{'ok': True, 'reason': '{job.get('_skip_reason') or 'skipped'}'}}"
                    )
                    continue
                try:
                    queued_at = float(job.get("queued_at") or 0.0)
                except Exception:
                    queued_at = 0.0
                try:
                    dequeued_at = float(job.get("_dequeued_at") or 0.0)
                except Exception:
                    dequeued_at = 0.0
                result = materialize_snapshot_for_school(
                    school_id=school_id,
                    rev=rev,
                    day_key=day_key,
                    queued_at=queued_at,
                    dequeued_at=dequeued_at,
                    source="worker",
                )
                self.stdout.write(
                    f"snapshot_worker_job school_id={school_id} requested_rev={rev} day_key={day_key} queue_wait_ms={int(result.get('queue_wait_ms') or 0)} process_ms={int(result.get('process_ms') or 0)} ok={int(bool(result.get('ok')))} result={result}"
                )
            finally:
                complete_snapshot_job(job)

            if once:
                return
