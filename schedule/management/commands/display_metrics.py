from __future__ import annotations

from django.core.cache import cache
from django.core.management.base import BaseCommand

from schedule.cache_utils import status_metrics_day_key, status_metrics_key


class Command(BaseCommand):
    help = "Print sampled /api/display/status cache-only metrics counters from cache (no DB)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--day",
            default="",
            help="Day key in YYYYMMDD (default: today).",
        )

    def handle(self, *args, **options):
        day = (options.get("day") or "").strip() or status_metrics_day_key()

        names = [
            "total",
            "rev_hit",
            "rev_miss",
            "fetch_required",
            "resolve_fail",
            "invalid_token",
        ]

        values: dict[str, int] = {}
        for n in names:
            k = status_metrics_key(day_key=day, name=n)
            try:
                values[n] = int(cache.get(k) or 0)
            except Exception:
                values[n] = 0

        total = max(0, values.get("total", 0))
        rev_hit = max(0, values.get("rev_hit", 0))
        rev_miss = max(0, values.get("rev_miss", 0))
        fetch_required = max(0, values.get("fetch_required", 0))
        resolve_fail = max(0, values.get("resolve_fail", 0))
        invalid_token = max(0, values.get("invalid_token", 0))

        def pct(num: int, den: int) -> str:
            if den <= 0:
                return "0.00%"
            return f"{(100.0 * float(num) / float(den)):.2f}%"

        rev_total = rev_hit + rev_miss

        self.stdout.write(f"day={day}")
        self.stdout.write(f"total={total}")
        self.stdout.write(f"rev_total={rev_total} (numeric mode sampled)")
        self.stdout.write(f"rev_hit={rev_hit} ({pct(rev_hit, rev_total)})")
        self.stdout.write(f"rev_miss={rev_miss} ({pct(rev_miss, rev_total)})")
        self.stdout.write(f"fetch_required={fetch_required} ({pct(fetch_required, total)})")
        self.stdout.write(f"resolve_fail={resolve_fail} ({pct(resolve_fail, total)})")
        self.stdout.write(f"invalid_token={invalid_token} ({pct(invalid_token, total)})")
