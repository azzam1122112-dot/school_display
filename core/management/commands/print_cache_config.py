from __future__ import annotations

import os

from django.conf import settings
from django.core.cache import caches
from django.core.management.base import BaseCommand


def _redact_location(value: object) -> object:
    if not isinstance(value, str):
        return value
    v = value.strip()
    if not v:
        return v
    try:
        if "@" in v and "://" in v:
            scheme, rest = v.split("://", 1)
            if rest.startswith(":") and "@" in rest:
                _cred, hostpart = rest.split("@", 1)
                return f"{scheme}://:***@{hostpart}"
    except Exception:
        pass
    return v


class Command(BaseCommand):
    help = "Print active Django cache backend and redacted settings.CACHES['default']."

    def handle(self, *args, **options):
        try:
            default_cfg = dict(getattr(settings, "CACHES", {}).get("default", {}) or {})
        except Exception:
            default_cfg = {}

        if "LOCATION" in default_cfg:
            default_cfg["LOCATION"] = _redact_location(default_cfg.get("LOCATION"))

        try:
            backend = caches["default"]
            backend_name = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
        except Exception:
            backend_name = "unknown"

        self.stdout.write(f"redis_url_configured={bool(os.getenv('REDIS_URL', '').strip())}")
        self.stdout.write(f"cache_backend={backend_name}")
        self.stdout.write(f"settings.CACHES['default']={default_cfg}")

        # Best-effort connectivity check for django-redis.
        try:
            from django_redis import get_redis_connection  # type: ignore

            conn = get_redis_connection("default")
            ok = bool(conn.ping())
            self.stdout.write(f"redis_ping_ok={ok}")
        except Exception as e:
            self.stdout.write(f"redis_ping_ok=False")
            self.stdout.write(f"redis_ping_error={str(e)[:200]}")
