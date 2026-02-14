# schedule/api_views.py
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import socket
import time
from datetime import time as dt_time
from typing import Iterable, Optional

from django.conf import settings as dj_settings
from django.core.cache import cache
from django.core.cache import caches
from django.db import models
from django.db.models import Q
from django.http import JsonResponse, HttpResponseNotModified
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

try:
    from django_redis import get_redis_connection
except ImportError:
    get_redis_connection = None

from core.models import School, DisplayScreen
from schedule.models import SchoolSettings, ClassLesson, Period
from schedule.time_engine import build_day_snapshot
from schedule.cache_utils import (
    get_cached_schedule_revision_for_school_id,
    set_cached_schedule_revision_for_school_id,
    status_metrics_bump,
    status_metrics_day_key,
    status_metrics_should_sample,
)

logger = logging.getLogger(__name__)


def _ttl_jitter_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_TTL_JITTER_SEC", os.getenv("DISPLAY_SNAPSHOT_TTL_JITTER_SEC", "0")) or 0)
    except Exception:
        v = 0
    return max(0, min(15, v))


def _stable_ttl_with_jitter(ttl: int, *, seed: str, ttl_max: int | None = None) -> int:
    """Return a TTL with a stable per-seed jitter.

    Goal: spread expirations across schools/screens to reduce peak load.
    Default jitter=0 => no behavior change.
    """
    try:
        ttl_i = int(ttl)
    except Exception:
        return ttl
    if ttl_i <= 1:
        return ttl_i

    jitter = _ttl_jitter_seconds()
    if jitter <= 0:
        return ttl_i

    # Stable delta in [0..jitter] derived from seed.
    try:
        h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
        delta = int(h[:8], 16) % (jitter + 1)
    except Exception:
        delta = 0

    out = ttl_i + int(delta)
    if ttl_max is not None:
        try:
            out = min(out, int(ttl_max))
        except Exception:
            pass
    return max(1, out)


def _cache_is_shared() -> bool:
    """Best-effort check whether the configured cache is shared across processes.

    In production we expect Redis (django-redis). If Redis isn't configured and
    LocMemCache is used, relying on cache-only revision comparisons can cause
    some devices (e.g., TVs) to never detect updates if they hit a different
    worker/process.
    """
    try:
        if str(getattr(dj_settings, "REDIS_URL", "") or "").strip():
            return True
    except Exception:
        pass
    try:
        default_cache = dj_settings.CACHES.get("default", {})
        backend = str(default_cache.get("BACKEND", "") or "").lower()
        return "django_redis" in backend or "rediscache" in backend
    except Exception:
        return False


def _log_cache_env(logger: logging.Logger) -> None:
    try:
        default_cache = dj_settings.CACHES.get("default", {})
        backend = str(default_cache.get("BACKEND", "") or "")
        location = str(default_cache.get("LOCATION", "") or "")
        safe_location = location.split("@")[-1] if location else ""
        logger.info(
            "cache_env backend=%s location=%s host=%s render_instance=%s",
            backend,
            safe_location,
            socket.gethostname(),
            os.getenv("RENDER_INSTANCE_ID", ""),
        )
    except Exception:
        try:
            logger.info("cache_env backend=unknown")
        except Exception:
            pass


def _steady_cache_log_enabled() -> bool:
    try:
        if bool(getattr(dj_settings, "DEBUG", False)):
            return True
    except Exception:
        pass
    return (os.getenv("DISPLAY_STEADY_CACHE_LOG", "").strip() == "1")


def _safe_snapshot_rollout_enabled() -> bool:
    try:
        return bool(getattr(dj_settings, "SNAPSHOT_STEADY_CACHE_V2", False))
    except Exception:
        return False


def _cache_backend_name() -> str:
    try:
        backend = caches["default"]
        return f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    except Exception:
        return f"{cache.__class__.__module__}.{cache.__class__.__name__}"


def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    # ✅ FIX: إعادة التاريخ للمفتاح لأن rev لا يتغير يومياً، مما قد يسبب عرض جدول الأمس
    # عند منتصف الليل، سيتغير التاريخ => cache miss => build new snapshot (صحيح)
    date_str = str(timezone.localdate())
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady:{date_str}"


def _get_stale_snapshot_fallback(school_id: int) -> dict | None:
    """
    ✅ Stale-While-Revalidate: محاولة إيجاد أي snapshot قديم للمدرسة
    عند cache miss، نعرض البيانات القديمة بدلاً من شاشة فارغة
    """
    # التأكد من توفر django_redis
    if get_redis_connection is None:
        return None
    
    try:
        # البحث عن أي نسخة قديمة من snapshot لنفس المدرسة (أي revision)
        # نستخدم pattern matching للبحث في الكاش
        redis_client = get_redis_connection("default")
        
        # البحث عن مفاتيح تطابق المدرسة
        pattern = f"school_display:snapshot:v5:school:{int(school_id)}:rev:*:steady"
        keys = redis_client.keys(pattern)
        
        if keys:
            # استخدام أول مفتاح متوفر (يمكن تحسينه باختيار الأحدث)
            stale_key = keys[0].decode('utf-8') if isinstance(keys[0], bytes) else keys[0]
            # إزالة الـ prefix إن وجد
            if stale_key.startswith("school_display:"):
                stale_key = stale_key[len("school_display:"):]
            
            stale_snap = cache.get(stale_key)
            if isinstance(stale_snap, dict):
                # إضافة تحذير للبيانات القديمة
                if "meta" not in stale_snap:
                    stale_snap["meta"] = {}
                stale_snap["meta"]["is_stale"] = True
                stale_snap["meta"]["stale_warning"] = "يتم تحديث البيانات..."
                return stale_snap
    except Exception as e:
        # فشل البحث عن snapshot قديم - لا مشكلة
        logger.debug(f"Stale snapshot lookup failed for school {school_id}: {e}")
    
    return None


def _log_steady_get(key: str, *, hit: bool, school_id: int | None, rev: int | None) -> None:
    if not _steady_cache_log_enabled():
        return
    try:
        # Throttle per key to avoid production log storms.
        throttle = f"log:steady_get:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
        if not bool(cache.add(throttle, "1", timeout=10)):
            return
    except Exception:
        pass
    try:
        logger.info(
            "steady_get key=%s hit=%s school_id=%s rev=%s backend=%s host=%s instance=%s",
            key,
            "1" if hit else "0",
            school_id,
            rev,
            _cache_backend_name(),
            socket.gethostname(),
            os.getenv("RENDER_INSTANCE_ID", ""),
        )
    except Exception:
        pass


def _log_steady_set(
    key: str,
    *,
    ttl: int,
    school_id: int | None,
    rev: int | None,
    success: bool = True,
    error: str = "",
) -> None:
    if not _steady_cache_log_enabled():
        return
    try:
        throttle = f"log:steady_set:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
        if not bool(cache.add(throttle, "1", timeout=10)):
            return
    except Exception:
        pass
    try:
        logger.info(
            "steady_set key=%s ttl=%s school_id=%s rev=%s success=%s error=%s backend=%s host=%s instance=%s",
            key,
            int(ttl),
            school_id,
            rev,
            "1" if success else "0",
            (error or "")[:80],
            _cache_backend_name(),
            socket.gethostname(),
            os.getenv("RENDER_INSTANCE_ID", ""),
        )
    except Exception:
        pass


def _metrics_interval_seconds() -> int:
    # Log cache hit/miss metrics at INFO at most once per N seconds.
    # Keep it conservative to avoid log noise in SaaS.
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC", os.getenv("DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC", "600")))
    except Exception:
        v = 600
    return max(60, min(3600, v))


def _status_log_interval_seconds() -> int:
    # For large fleets, logging every status poll is too noisy.
    # Default: log at most once per token per 5 minutes.
    try:
        v = int(getattr(dj_settings, "DISPLAY_STATUS_LOG_INTERVAL_SEC", os.getenv("DISPLAY_STATUS_LOG_INTERVAL_SEC", "300")))
    except Exception:
        v = 300
    return max(30, min(3600, v))


def _status_log_interval_200_seconds() -> int:
    # Status 200 can spike during update waves; use a shorter dedicated window.
    try:
        v = int(getattr(dj_settings, "DISPLAY_STATUS_200_LOG_INTERVAL_SEC", os.getenv("DISPLAY_STATUS_200_LOG_INTERVAL_SEC", "120")))
    except Exception:
        v = 120
    return max(10, min(3600, v))


def _status_warn_log_interval_seconds() -> int:
    # Operational warnings should be visible but still throttled at fleet scale.
    try:
        v = int(getattr(dj_settings, "DISPLAY_STATUS_WARN_LOG_INTERVAL_SEC", os.getenv("DISPLAY_STATUS_WARN_LOG_INTERVAL_SEC", "300")))
    except Exception:
        v = 300
    return max(30, min(3600, v))


def _should_log_status(token_hash: str, *, interval: int | None = None) -> bool:
    interval = int(interval if interval is not None else _status_log_interval_seconds())
    key = f"log:status_poll:{token_hash[:12]}:{interval}"
    try:
        return bool(cache.add(key, "1", timeout=interval))
    except Exception:
        return True


def _should_log_status_200_school_rev(*, school_id: int, rev: int) -> bool:
    """Throttle noisy status=200 logs for large fleets.

    We want at most one INFO log per (school_id, rev) per interval regardless
    of how many screens poll.
    """
    interval = _status_log_interval_200_seconds()
    if not school_id:
        return True
    try:
        key = f"log:status_poll_200:{int(school_id)}:{int(rev)}:{int(interval)}"
        return bool(cache.add(key, "1", timeout=interval))
    except Exception:
        return True


def _get_school_revision_cache_only(school_id: int) -> tuple[int | None, str]:
    """Return (revision, source) without any DB fallback.

    This keeps /api/display/status cache-only. If revision cache is missing,
    we return (None, "none") and let the client fetch snapshot.
    """
    if not school_id:
        return None, "none"

    _metrics_incr("metrics:status:cache_get")
    try:
        cached = get_cached_schedule_revision_for_school_id(int(school_id))
    except Exception:
        cached = None
    if cached is not None:
        _metrics_incr("metrics:status:rev_cache_hit")
        return int(cached), "cache"
    _metrics_incr("metrics:status:rev_none")
    return None, "none"


def _should_log_status_304_sample(token_hash: str) -> bool:
    # ~1% sampling based on token hash prefix.
    try:
        return int(token_hash[:2], 16) < 3  # 3/256 ≈ 1.17%
    except Exception:
        return False


def _get_school_revision_cached(school_id: int) -> tuple[int | None, str]:
    """Return (revision, source) where source is cache|db|none."""
    if not school_id:
        return None, "none"

    # If cache is not shared (e.g. LocMemCache), do not trust cached values.
    # Always refresh from DB to ensure all workers see updates.
    if _cache_is_shared():
        _metrics_incr("metrics:status:cache_get")
        cached = get_cached_schedule_revision_for_school_id(int(school_id))
        if cached is not None:
            _metrics_incr("metrics:status:rev_cache_hit")
            return int(cached), "cache"

    try:
        _metrics_incr("metrics:status:rev_db")
        rev = int(
            SchoolSettings.objects.filter(school_id=int(school_id)).values_list("schedule_revision", flat=True).first()
            or 0
        )
        _metrics_incr("metrics:status:cache_set")
        set_cached_schedule_revision_for_school_id(int(school_id), int(rev))
        return int(rev), "db"
    except Exception:
        _metrics_incr("metrics:status:rev_none")
        return None, "none"

def _metrics_incr(key: str) -> None:
    try:
        cache.incr(key)
    except Exception:
        try:
            cache.add(key, 1, timeout=60 * 60 * 24)
        except Exception:
            pass


@require_GET
def metrics(request):
    """Expose internal counters for load testing / debugging.

    Disabled by default in production.
    - Enabled when DEBUG=True OR DISPLAY_METRICS_ENABLED=1
    - Optional auth via DISPLAY_METRICS_KEY + X-Display-Metrics-Key header
    """
    is_debug = bool(getattr(dj_settings, "DEBUG", False))
    enabled_flag = (os.getenv("DISPLAY_METRICS_ENABLED", "").strip() == "1")

    # Production: endpoint is OFF unless explicitly enabled.
    # When enabled in production, a key is mandatory.
    if (not is_debug) and (not enabled_flag):
        return JsonResponse({"detail": "not_found"}, status=404)

    required_key = os.getenv("DISPLAY_METRICS_KEY", "").strip()
    if (not is_debug) and (not required_key):
        return JsonResponse({"detail": "not_found"}, status=404)

    if required_key:
        provided = (request.headers.get("X-Display-Metrics-Key") or "").strip()
        if provided != required_key:
            return JsonResponse({"detail": "forbidden"}, status=403)

    keys = [
        "metrics:status:requests",
        "metrics:status:resp_200",
        "metrics:status:resp_304",
        "metrics:status:cache_get",
        "metrics:status:cache_set",
        "metrics:status:rev_cache_hit",
        "metrics:status:rev_db",
        "metrics:status:rev_none",

        # Snapshot cache counters
        "metrics:snapshot_cache:token_hit",
        "metrics:snapshot_cache:token_miss",
        "metrics:snapshot_cache:school_hit",
        "metrics:snapshot_cache:school_miss",
        "metrics:snapshot_cache:steady_hit",
        "metrics:snapshot_cache:steady_miss",

        # Snapshot build metrics
        "metrics:snapshot_cache:build_count",
        "metrics:snapshot_cache:build_sum_ms",
        "metrics:snapshot_cache:build_max_ms",
    ]

    try:
        backend = caches["default"]
        backend_name = f"{backend.__class__.__module__}.{backend.__class__.__name__}"
    except Exception:
        backend_name = f"{cache.__class__.__module__}.{cache.__class__.__name__}"

    out: dict[str, object] = {
        "server_time": int(time.time()),
        "hostname": (socket.gethostname() or "").strip(),
        "process_id": int(os.getpid()),
        "cache_backend": backend_name,
        "redis_url_configured": bool(os.getenv("REDIS_URL", "").strip()),
        "cache_key_prefix": os.getenv("CACHE_KEY_PREFIX", "school_display"),
    }

    def _sanitize_error(msg: str) -> str:
        # Avoid leaking connection strings or credentials in metrics output.
        try:
            s = (msg or "").strip()
            if not s:
                return ""
            # Redact any redis/rediss URLs.
            for scheme in ("redis://", "rediss://"):
                if scheme in s:
                    # Keep only scheme and a marker.
                    s = s.replace(scheme, scheme + "***")
            return s[:200]
        except Exception:
            return ""

    # Optional: validate Redis connectivity (best-effort, no hard dependency).
    # This helps distinguish "Redis configured" vs "Redis actually reachable".
    try:
        from django_redis import get_redis_connection  # type: ignore

        t0 = time.monotonic()
        conn = get_redis_connection("default")
        ok = bool(conn.ping())
        out["redis_ping_ok"] = ok
        out["redis_ping_ms"] = int((time.monotonic() - t0) * 1000)
    except Exception as e:
        out["redis_ping_ok"] = False
        out["redis_ping_error"] = e.__class__.__name__
        out["redis_ping_error_detail"] = _sanitize_error(str(e))

    # Optional: shared-cache probe.
    # If you call metrics repeatedly and see different process_id values but the same probe_last,
    # that's strong evidence the cache is shared across workers.
    try:
        probe = (request.GET.get("probe") or "").strip().lower() in {"1", "true", "yes"}
        if not probe:
            probe = (request.headers.get("X-Display-Metrics-Probe") or "").strip().lower() in {"1", "true", "yes"}
        if probe:
            probe_key = f"metrics:cache_probe:{os.getenv('CACHE_KEY_PREFIX', 'school_display')}"
            prev = cache.get(probe_key)
            out["cache_probe_last"] = prev
            payload = {"pid": int(os.getpid()), "ts": int(time.time())}
            cache.set(probe_key, payload, timeout=120)
            out["cache_probe_written"] = payload
    except Exception as e:
        out["cache_probe_error"] = str(e)[:200]

    for k in keys:
        try:
            v = cache.get(k)
            out[k] = int(v) if v is not None else 0
        except Exception:
            out[k] = 0

    # Derived metrics
    try:
        bc = int(out.get("metrics:snapshot_cache:build_count", 0) or 0)
        bsum = int(out.get("metrics:snapshot_cache:build_sum_ms", 0) or 0)
        out["metrics:snapshot_cache:build_avg_ms"] = int(bsum / bc) if bc > 0 else 0
    except Exception:
        out["metrics:snapshot_cache:build_avg_ms"] = 0

    return JsonResponse(out, json_dumps_params={"ensure_ascii": False})


@require_http_methods(["GET"])
def ws_metrics(request):
    """
    GET /api/display/ws-metrics/
    
    Returns WebSocket metrics for monitoring/dashboards.
    
    Response:
    {
        "connections_active": 1234,
        "connections_total": 5678,
        "connections_failed": 12,
        "broadcasts_sent": 8901,
        "broadcasts_failed": 3,
        "broadcast_latency_avg_ms": 0.5,
        "health": "ok|warning|critical"
    }
    """
    try:
        from display.ws_metrics import ws_metrics as metrics_tracker
        
        metrics = metrics_tracker.get_snapshot()
        
        # Calculate derived metrics
        active = metrics.get("connections_active", 0)
        failed = metrics.get("connections_failed", 0)
        total = max(1, metrics.get("connections_total", 1))  # Avoid division by zero
        
        broadcasts_sent = metrics.get("broadcasts_sent", 0)
        broadcasts_failed = metrics.get("broadcasts_failed", 0)
        
        avg_latency = 0.0
        if metrics.get("broadcast_latency_count", 0) > 0:
            avg_latency = (
                metrics.get("broadcast_latency_sum", 0) / 
                metrics["broadcast_latency_count"]
            )
        
        # Health status
        health = "ok"
        if active == 0 and total > 10:
            health = "warning"  # No connections but had connections before
        elif failed / total > 0.1:  # > 10% connection failure rate
            health = "critical"
        elif broadcasts_failed / max(1, broadcasts_sent + broadcasts_failed) > 0.05:  # > 5% broadcast failures
            health = "warning"
        elif avg_latency > 100:  # Broadcast latency > 100ms
            health = "warning"
        
        return JsonResponse({
            "connections_active": active,
            "connections_total": total,
            "connections_failed": failed,
            "broadcasts_sent": broadcasts_sent,
            "broadcasts_failed": broadcasts_failed,
            "broadcast_latency_avg_ms": round(avg_latency, 2),
            "health": health,
        })
    except ImportError:
        # ws_metrics not available (channels not installed/configured)
        return JsonResponse({
            "error": "WebSocket metrics not available",
            "detail": "Channels not configured or DISPLAY_WS_ENABLED=false"
        }, status=503)
    except Exception as e:
        logger.exception(f"ws_metrics error: {e}")
        return JsonResponse({"error": "Internal error"}, status=500)


def _metrics_add(key: str, delta: int) -> None:
    try:
        cache.incr(key, int(delta))
    except Exception:
        try:
            cur = cache.get(key) or 0
            cache.set(key, int(cur) + int(delta), timeout=60 * 60 * 24)
        except Exception:
            pass


def _metrics_set_max(key: str, value: int) -> None:
    try:
        cur = cache.get(key)
        cur_i = int(cur) if cur is not None else 0
        v = int(value)
        if v > cur_i:
            cache.set(key, v, timeout=60 * 60 * 24)
    except Exception:
        pass

def _metrics_log_maybe() -> None:
    interval = _metrics_interval_seconds()
    throttle_key = f"metrics:snapshot_cache:log:{interval}"
    try:
        should_log = bool(cache.add(throttle_key, "1", timeout=interval))
    except Exception:
        should_log = False

    if not should_log:
        return

    keys = [
        "metrics:snapshot_cache:token_hit",
        "metrics:snapshot_cache:token_miss",
        "metrics:snapshot_cache:school_hit",
        "metrics:snapshot_cache:school_miss",
        "metrics:snapshot_cache:steady_hit",
        "metrics:snapshot_cache:steady_miss",
        "metrics:snapshot_cache:build_count",
        "metrics:snapshot_cache:build_sum_ms",
        "metrics:snapshot_cache:build_max_ms",
    ]
    try:
        vals = {k: (cache.get(k) or 0) for k in keys}
    except Exception:
        vals = {k: 0 for k in keys}

    build_count = int(vals.get(keys[6], 0) or 0)
    build_sum_ms = int(vals.get(keys[7], 0) or 0)
    build_max_ms = int(vals.get(keys[8], 0) or 0)
    build_avg_ms = int(build_sum_ms / build_count) if build_count > 0 else 0

    logger.info(
        "snapshot_cache metrics token_hit=%s token_miss=%s school_hit=%s school_miss=%s steady_hit=%s steady_miss=%s build_count=%s build_avg_ms=%s build_max_ms=%s",
        vals.get(keys[0], 0),
        vals.get(keys[1], 0),
        vals.get(keys[2], 0),
        vals.get(keys[3], 0),
        vals.get(keys[4], 0),
        vals.get(keys[5], 0),
        build_count,
        build_avg_ms,
        build_max_ms,
    )


def _snapshot_ttl_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_TTL", 10) or 10)
    except Exception:
        v = 10
    return max(1, min(60, v))


def _snapshot_build_lock_ttl_seconds() -> int:
    # Short lock to coalesce concurrent requests.
    return 8


def _snapshot_bind_ttl_seconds() -> int:
    # How long a token stays bound to the first seen device_key.
    return 60 * 60 * 24 * 30  # 30 days


def _stable_json_bytes(payload: dict) -> bytes:
    # Stable encoding for ETag hashing (order-independent).
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _etag_from_json_bytes(json_bytes: bytes) -> str:
    return hashlib.sha256(json_bytes).hexdigest()


def _parse_if_none_match(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    # We only support a single strong ETag value.
    if s.startswith("W/"):
        s = s[2:].strip()
    if s.startswith('"') and s.endswith('"') and len(s) > 1:
        s = s[1:-1]
    if not s:
        return None
    return s


def _snapshot_anti_loop_check(token_hash: str) -> bool:
    """
    Checks if a token is requesting too frequently (looping).
    Returns True if safe, False if looping (should receive cool-down).
    Limit: 30 requests per minute.
    """
    key = f"loop:{token_hash}"
    try:
        # 60 seconds rolling window (approx)
        added = cache.add(key, 1, timeout=60)
        if added:
            val = 1
        else:
            val = cache.incr(key)
        
        if val > 30: 
            return False
        return True
    except Exception:
        return True


def _snapshot_rate_limit_allow(token_hash: str, device_hash: str) -> bool:
    """Token bucket: 1 req/sec with burst 3, keyed by token_hash + device_hash."""

    capacity = 3.0
    refill_per_sec = 1.0
    state_key = f"rl:snapshot:{token_hash}:{device_hash}"
    lock_key = f"{state_key}:lock"

    now = time.monotonic()
    state = None

    have_lock = False
    try:
        have_lock = bool(cache.add(lock_key, "1", timeout=1))
    except Exception:
        have_lock = False

    if not have_lock:
        # Best effort: if we can't lock, avoid hard-failing the request.
        return True

    try:
        state = cache.get(state_key)
        if not isinstance(state, dict):
            state = {"tokens": capacity, "ts": now}

        tokens = float(state.get("tokens", capacity))
        last_ts = float(state.get("ts", now))

        elapsed = max(0.0, now - last_ts)
        tokens = min(capacity, tokens + elapsed * refill_per_sec)

        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0

        state = {"tokens": tokens, "ts": now}
        try:
            cache.set(state_key, state, timeout=60)
        except Exception:
            pass

        return allowed
    finally:
        try:
            cache.delete(lock_key)
        except Exception:
            pass


def _app_revision() -> str:
    try:
        v = str(getattr(dj_settings, "APP_REVISION", "") or "").strip()
    except Exception:
        v = ""
    return v


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        for k in ("items", "results", "data", "rows", "list"):
            v = value.get(k)
            if isinstance(v, list):
                return v
    return []


def _normalize_snapshot_keys(snap: dict) -> dict:
    """
    مفاتيح ثابتة للواجهة:
      - announcements
      - excellence
      - standby
      - period_classes
      - day_path
    """
    if not isinstance(snap, dict):
        return {
            "settings": {},
            "state": {},
            "day_path": [],
            "current_period": None,
            "next_period": None,
            "period_classes": [],
            "standby": [],
            "excellence": [],
            "announcements": [],
        }

    for container_key in ("data", "payload", "result", "snapshot"):
        c = snap.get(container_key)
        if isinstance(c, dict):
            for k, v in c.items():
                snap.setdefault(k, v)

    def fill(dst_key: str, source_keys):
        cur = _as_list(snap.get(dst_key))
        if cur:
            snap[dst_key] = cur
            return
        for k in source_keys:
            arr = _as_list(snap.get(k))
            if arr:
                snap[dst_key] = arr
                return
        snap[dst_key] = []

    fill(
        "excellence",
        ["honor_board", "excellence_board", "honors", "awards", "excellent", "excellent_students", "honor_items"],
    )
    fill(
        "standby",
        ["waiting", "standby_periods", "standby_items", "standby_list", "standbyClasses", "standby_classes"],
    )
    fill(
        "announcements",
        ["alerts", "notices", "messages", "announcement_list", "announcements_list"],
    )

    snap["day_path"] = _as_list(snap.get("day_path"))
    snap["period_classes"] = _as_list(snap.get("period_classes"))
    return snap


def _fallback_payload(message: str = "إعدادات المدرسة غير مهيأة") -> dict:
    now = timezone.localtime()
    return {
        "now": now.isoformat(),
        "meta": {"weekday": now.isoweekday(), "schedule_revision": 0},
        "settings": {
            "name": "",
            "logo_url": None,
            "theme": "indigo",
            "refresh_interval_sec": 10,
            "standby_scroll_speed": 0.8,
            "periods_scroll_speed": 0.5,
        },
        "state": {
            "type": "config",
            "label": message,
            "from": None,
            "to": None,
            "remaining_seconds": 0,
        },
        "day_path": [],
        "current_period": None,
        "next_period": None,
        "period_classes": [],
        "standby": [],
        "excellence": [],
        "announcements": [],
    }


def _fallback_building_payload(
    *,
    school_id: int,
    rev: int,
    day_key: str,
    reason: str = "building",
    refresh_interval_sec: int = 3,
) -> dict:
    """DB-free safe snapshot payload to avoid black screens during rebuilds."""

    payload = _fallback_payload("جاري تجهيز الجدول...")
    try:
        payload["settings"]["refresh_interval_sec"] = int(refresh_interval_sec)
    except Exception:
        pass
    try:
        meta = payload.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            payload["meta"] = meta
        meta["school_id"] = int(school_id)
        meta["schedule_revision"] = int(rev)
        meta["day_key"] = str(day_key)
        meta["cache"] = "FALLBACK"
        meta["reason"] = str(reason)
        meta["generated_at"] = timezone.now().isoformat()
    except Exception:
        pass
    try:
        st = payload.get("state")
        if isinstance(st, dict):
            st["type"] = "BUILDING"
            st["label"] = "جاري تجهيز الجدول..."
    except Exception:
        pass
    return payload


def _extract_token(request, token_from_path: str | None) -> str | None:
    t = (token_from_path or "").strip()

    # Fallback: some callers may embed token in the URL path while not passing it
    # via query/header (or if the URL pattern changes). Parse it from the path.
    if not t:
        try:
            p = (getattr(request, "path_info", "") or getattr(request, "path", "") or "").strip()
            m = re.search(r"/api/display/(?:snapshot|today|live|status)/([^/]+)/?$", p, flags=re.IGNORECASE)
            if m and m.group(1):
                t = (m.group(1) or "").strip()
        except Exception:
            pass

    if not t:
        t = (request.headers.get("X-Display-Token") or "").strip()
    if not t:
        t = (request.GET.get("token") or "").strip()
    if not t or len(t) < 8 or len(t) > 256:
        return None
    return t


@require_http_methods(["GET", "HEAD"])
def status(request, token: str | None = None):
    """Lightweight polling endpoint.

    GET /api/display/status/?token=...   (or X-Display-Token header)
    GET /api/display/status/<token>/

        Behavior (authoritative numeric revision mode):
        - When client sends `v=<schedule_revision>`:
                - return 304 ONLY if v == current schedule_revision
                - else return 200 with {fetch_required: true, schedule_revision: current_rev}
            This path intentionally ignores If-None-Match/ETag for status.

        Backward compatibility:
        - If `v` is missing, we keep legacy behavior (ETag-based) for older clients.

    This endpoint never builds snapshots and should stay cheap.
    """
    # --- Optional lightweight metrics (sampled, cache-only) ---
    def _metrics_enabled() -> bool:
        try:
            return bool(getattr(dj_settings, "DISPLAY_STATUS_METRICS_ENABLED", False))
        except Exception:
            return False

    def _metrics_sample_every() -> int:
        try:
            return int(getattr(dj_settings, "DISPLAY_STATUS_METRICS_SAMPLE_EVERY", 50) or 50)
        except Exception:
            return 50

    def _metrics_ttl() -> int:
        try:
            return int(getattr(dj_settings, "DISPLAY_STATUS_METRICS_KEY_TTL", 86400) or 86400)
        except Exception:
            return 86400

    def _invalid_token_signature() -> str:
        # Safe, non-PII signature used only for deterministic sampling.
        # Prefer the provided token (even if invalid length), else mix in path + UA.
        try:
            p = (token or "").strip()
        except Exception:
            p = ""
        try:
            if not p:
                p = (request.GET.get("token") or "").strip()
        except Exception:
            pass
        try:
            if not p:
                p = (request.headers.get("X-Display-Token") or "").strip()
        except Exception:
            pass
        try:
            path = (getattr(request, "path_info", "") or getattr(request, "path", "") or "").strip()
        except Exception:
            path = ""
        try:
            ua = (request.headers.get("User-Agent") or "").strip()
        except Exception:
            ua = ""
        return f"{p}|{path}|{ua}"

    token_value = _extract_token(request, token)
    if not token_value:
        # Sampled metrics for invalid_token to avoid becoming a Redis surface for spam.
        try:
            if _metrics_enabled():
                sig_hash = _sha256(_invalid_token_signature())
                if status_metrics_should_sample(token_hash=sig_hash, sample_every=_metrics_sample_every()):
                    day_key = status_metrics_day_key()
                    ttl = _metrics_ttl()
                    status_metrics_bump(day_key=str(day_key), name="invalid_token", ttl_sec=int(ttl))
        except Exception:
            pass

        try:
            p = (getattr(request, "path_info", "") or getattr(request, "path", "") or "").strip()
            logger.warning("status: invalid_token path=%s", p)
        except Exception:
            pass
        return JsonResponse({"detail": "invalid_token"}, status=403)

    _metrics_incr("metrics:status:requests")

    token_hash = _sha256(token_value)

    # Token-scoped manual refresh: if set, force fetch_required regardless of revision.
    # Used by dashboard "refresh single screen".
    force_key = f"display:force_refresh:{token_hash}"
    force_refresh = False
    try:
        force_refresh = bool(cache.get(force_key))
        if force_refresh:
            try:
                cache.delete(force_key)
            except Exception:
                pass
    except Exception:
        force_refresh = False

    # Token-scoped manual reload: force a full page reload on the client.
    reload_key = f"display:force_reload:{token_hash}"
    force_reload = False
    try:
        force_reload = bool(cache.get(reload_key))
        if force_reload:
            try:
                cache.delete(reload_key)
            except Exception:
                pass
    except Exception:
        force_reload = False

    # --- Optional lightweight metrics (sampled, cache-only) ---
    metrics_day_key = None
    metrics_ttl = None
    if _metrics_enabled():
        metrics_ttl = _metrics_ttl()
        if status_metrics_should_sample(token_hash=token_hash, sample_every=_metrics_sample_every()):
            metrics_day_key = status_metrics_day_key()

    def _bump_metric(name: str) -> None:
        if not metrics_day_key or not metrics_ttl:
            return
        status_metrics_bump(day_key=str(metrics_day_key), name=str(name), ttl_sec=int(metrics_ttl))

    # --- Numeric revision mode (source of truth) ---
    client_v_raw = (request.GET.get("v") or request.GET.get("rev") or "").strip()
    client_v = None
    try:
        if client_v_raw != "":
            client_v = int(client_v_raw)
    except Exception:
        client_v = None

    # Resolve school_id cheaply (prefer cache map)
    school_id = None
    try:
        _metrics_incr("metrics:status:cache_get")
        cached_map = cache.get(f"display:token_map:{token_hash}")
        if isinstance(cached_map, dict):
            school_id = cached_map.get("school_id")
        else:
            try:
                school_id = int(cached_map) if cached_map else None
            except Exception:
                school_id = None
    except Exception:
        school_id = None

    # If cache is not shared (LocMem / missing Redis), fall back to DB so different
    # workers/processes don't disagree and leave some devices stuck.
    if (not school_id) and (not _cache_is_shared()):
        try:
            qs = DisplayScreen.objects.filter(is_active=True)
            # Prefer exact token match; short_code is not expected here (token length check in _extract_token).
            scr = qs.filter(token__iexact=token_value).only("school_id").first()
            if scr and getattr(scr, "school_id", None):
                school_id = int(scr.school_id)
                try:
                    cache.set(f"display:token_map:{token_hash}", {"school_id": int(school_id)}, timeout=60 * 60)
                except Exception:
                    pass
        except Exception:
            school_id = school_id

    if client_v is not None:
        if _cache_is_shared():
            current_rev, rev_source = _get_school_revision_cache_only(int(school_id or 0))
        else:
            current_rev, rev_source = _get_school_revision_cached(int(school_id or 0))

        _bump_metric("total")

        resolve_failed = not bool(school_id)
        if resolve_failed:
            _bump_metric("resolve_fail")

        # If we couldn't resolve school_id, we can't compare; force fetch.
        if current_rev is None:
            if not resolve_failed:
                _bump_metric("rev_miss")
            _bump_metric("fetch_required")
            resp = JsonResponse({"fetch_required": True}, json_dumps_params={"ensure_ascii": False})
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            try:
                resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
            except Exception:
                pass
            # Throttle warnings to avoid log storms if token->school mapping is missing.
            if _should_log_status(token_hash, interval=_status_warn_log_interval_seconds()):
                logger.warning(
                    "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
                    token_hash[:12],
                    school_id,
                    client_v,
                    current_rev,
                    rev_source,
                    200,
                )
            return resp

        # If a manual force-refresh was requested, always require a fetch.
        if force_reload:
            _bump_metric("fetch_required")
            resp = JsonResponse(
                {"fetch_required": True, "schedule_revision": int(current_rev or 0), "reload": True},
                json_dumps_params={"ensure_ascii": False},
            )
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            try:
                resp["X-Schedule-Revision"] = str(int(current_rev or 0))
            except Exception:
                pass
            try:
                resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
            except Exception:
                pass
            _metrics_incr("metrics:status:resp_200")
            return resp

        if force_refresh:
            _bump_metric("fetch_required")
            resp = JsonResponse(
                {"fetch_required": True, "schedule_revision": int(current_rev or 0)},
                json_dumps_params={"ensure_ascii": False},
            )
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            try:
                resp["X-Schedule-Revision"] = str(int(current_rev or 0))
            except Exception:
                pass
            try:
                resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
            except Exception:
                pass
            _metrics_incr("metrics:status:resp_200")
            return resp

        if int(client_v) == int(current_rev):
            _bump_metric("rev_hit")
            resp = HttpResponseNotModified()
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            resp["X-Schedule-Revision"] = str(int(current_rev))
            try:
                resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
            except Exception:
                pass
            _metrics_incr("metrics:status:resp_304")
            # Do NOT log 304s except sampling.
            if _should_log_status_304_sample(token_hash) and _should_log_status(token_hash):
                logger.info(
                    "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
                    token_hash[:12],
                    int(school_id or 0),
                    int(client_v),
                    int(current_rev),
                    rev_source,
                    304,
                )
            return resp

        _bump_metric("rev_hit")
        _bump_metric("fetch_required")
        resp = JsonResponse(
            {"fetch_required": True, "schedule_revision": int(current_rev)},
            json_dumps_params={"ensure_ascii": False},
        )
        resp["Cache-Control"] = "no-store"
        resp["Vary"] = "Accept-Encoding"
        resp["X-Schedule-Revision"] = str(int(current_rev))
        try:
            resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
        except Exception:
            pass
        _metrics_incr("metrics:status:resp_200")
        # Log 200 updates, but throttle to once per (school_id, rev) per interval.
        if _should_log_status_200_school_rev(school_id=int(school_id or 0), rev=int(current_rev)):
            logger.info(
                "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
                token_hash[:12],
                int(school_id or 0),
                int(client_v),
                int(current_rev),
                rev_source,
                200,
            )
        return resp
    cache_key = get_cache_key(token_hash)

    cached_entry = cache.get(cache_key)
    if isinstance(cached_entry, dict) and isinstance(cached_entry.get("etag"), str):
        # ✅ Critical: if schedule revision changed, never return 304.
        # Otherwise the client will keep using old JSON forever.
        try:
            current_school_id = None
            cached_map = cache.get(f"display:token_map:{token_hash}")
            if isinstance(cached_map, dict):
                current_school_id = cached_map.get("school_id")
            else:
                try:
                    current_school_id = int(cached_map) if cached_map else None
                except Exception:
                    current_school_id = None

            # Cache-only: if revision cache is missing, force fetch_required.
            current_rev = get_cached_schedule_revision_for_school_id(int(current_school_id)) if current_school_id else None
            cached_rev = cached_entry.get("rev")
            if current_rev is None:
                resp = JsonResponse({"fetch_required": True}, json_dumps_params={"ensure_ascii": False})
                resp["Cache-Control"] = "no-store"
                resp["Vary"] = "Accept-Encoding"
                try:
                    resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
                except Exception:
                    pass
                return resp
            if cached_rev is not None and int(current_rev) != int(cached_rev):
                resp = JsonResponse(
                    {"fetch_required": True, "schedule_revision": int(current_rev)},
                    json_dumps_params={"ensure_ascii": False},
                )
                resp["Cache-Control"] = "no-store"
                resp["Vary"] = "Accept-Encoding"
                try:
                    resp["X-Schedule-Revision"] = str(int(current_rev))
                except Exception:
                    pass
                try:
                    resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
                except Exception:
                    pass
                return resp
        except Exception:
            pass

        inm = _parse_if_none_match(request.headers.get("If-None-Match"))
        etag = cached_entry.get("etag")
        if inm and etag and inm == etag:
            resp = HttpResponseNotModified()
            resp["ETag"] = f"\"{etag}\""
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            try:
                resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
            except Exception:
                pass
            _metrics_incr("metrics:status:resp_304")
            if _should_log_status_304_sample(token_hash) and _should_log_status(token_hash):
                logger.info(
                    "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
                    token_hash[:12],
                    current_school_id,
                    None,
                    current_rev,
                    "legacy",
                    304,
                )
            return resp

        resp = JsonResponse({"fetch_required": True, "etag": etag}, json_dumps_params={"ensure_ascii": False})
        resp["Cache-Control"] = "no-store"
        resp["Vary"] = "Accept-Encoding"
        try:
            if current_rev is not None:
                resp["X-Schedule-Revision"] = str(int(current_rev or 0))
        except Exception:
            pass
        try:
            resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
        except Exception:
            pass
        _metrics_incr("metrics:status:resp_200")
        try:
            sid = int(current_school_id or 0)
            revv = int(current_rev or 0)
        except Exception:
            sid = 0
            revv = 0
        if (sid and _should_log_status_200_school_rev(school_id=sid, rev=revv)) or (not sid and _should_log_status(token_hash)):
            logger.info(
                "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
                token_hash[:12],
                current_school_id,
                None,
                current_rev,
                "legacy",
                200,
            )
        return resp

    resp = JsonResponse({"fetch_required": True}, json_dumps_params={"ensure_ascii": False})
    resp["Cache-Control"] = "no-store"
    resp["Vary"] = "Accept-Encoding"
    try:
        resp["X-Server-Time-MS"] = str(int(timezone.now().timestamp() * 1000))
    except Exception:
        pass
    _metrics_incr("metrics:status:resp_200")
    if _should_log_status(token_hash):
        logger.info(
            "status_poll token_hash=%s school_id=%s client_v=%s current_rev=%s rev_source=%s resp=%s",
            token_hash[:12],
            school_id,
            None,
            None,
            "none",
            200,
        )
    return resp


def _is_hex_sha256(token_value: str) -> bool:
    if not token_value or len(token_value) != 64:
        return False
    try:
        int(token_value, 16)
        return True
    except Exception:
        return False


def _candidate_fields_for_model(model_cls) -> list[str]:
    keywords = ("token", "key", "api", "secret", "hash", "code", "slug")
    fields: list[str] = []
    for f in model_cls._meta.fields:
        if isinstance(f, (models.CharField, models.TextField)):
            n = f.name.lower()
            if any(k in n for k in keywords):
                fields.append(f.name)
    return fields


def _get_settings_by_school_id(school_id: int) -> SchoolSettings | None:
    return (
        SchoolSettings.objects.select_related("school")
        .filter(school_id=school_id)
        .first()
    )


def _get_schedule_revision_for_school_id(school_id: int) -> int:
    if not school_id:
        return 0
    # Cache-first to avoid repeated DB hits during snapshot polling.
    try:
        cached = get_cached_schedule_revision_for_school_id(int(school_id))
        if cached is not None:
            return int(cached)
    except Exception:
        pass
    try:
        rev = int(
            SchoolSettings.objects.filter(school_id=int(school_id)).values_list("schedule_revision", flat=True).first()
            or 0
        )
    except Exception:
        rev = 0
    try:
        set_cached_schedule_revision_for_school_id(int(school_id), int(rev))
    except Exception:
        pass
    return int(rev)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _token_variants_for_school_ids(school_id: int) -> Iterable[str]:
    secret = getattr(dj_settings, "DISPLAY_TOKEN_SALT", "") or dj_settings.SECRET_KEY
    sid = str(school_id)
    patterns = [
        f"{sid}:{secret}",
        f"{secret}:{sid}",
        f"display:{sid}:{secret}",
        f"{sid}{secret}",
        f"{secret}{sid}",
    ]
    for p in patterns:
        yield _sha256(p)


def _match_settings_by_hash_token(token_value: str) -> SchoolSettings | None:
    if not _is_hex_sha256(token_value):
        return None

    qs = SchoolSettings.objects.select_related("school").only("id", "school_id")
    for ss in qs:
        for v in _token_variants_for_school_ids(ss.school_id):
            if v == token_value:
                return SchoolSettings.objects.select_related("school").get(pk=ss.pk)
    return None


def _get_settings_by_token(token_value: str) -> SchoolSettings | None:
    if not token_value:
        return None

    ss_fields = _candidate_fields_for_model(SchoolSettings)
    if ss_fields:
        q = Q()
        for name in ss_fields:
            q |= Q(**{name: token_value})
        obj = SchoolSettings.objects.select_related("school").filter(q).first()
        if obj:
            return obj

    s_fields = _candidate_fields_for_model(School)
    if s_fields:
        q = Q()
        for name in s_fields:
            q |= Q(**{name: token_value})
        school = School.objects.filter(q).first()
        if school:
            return _get_settings_by_school_id(school.id)

    obj = _match_settings_by_hash_token(token_value)
    if obj:
        return obj

    return None


def _abs_media_url(request, maybe_url: str | None) -> str | None:
    if not maybe_url:
        return None
    s = str(maybe_url).strip()
    if s.lower() in {"none", "null", "-"}:
        return None
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s.replace("http://", "//").replace("https://", "//")
    try:
        return request.build_absolute_uri(s)
    except Exception:
        return s


def _model_has_field(model_cls, field_name: str) -> bool:
    try:
        model_cls._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _get_active_screens_qs():
    qs = DisplayScreen.objects.all()
    if _model_has_field(DisplayScreen, "is_active"):
        qs = qs.filter(is_active=True)
    return qs.select_related("school")


def _match_settings_via_display_screen(token_value: str) -> Optional[SchoolSettings]:
    if not token_value:
        return None

    only_fields = ["id", "school_id"]
    if _model_has_field(DisplayScreen, "token"):
        only_fields.append("token")

    qs = _get_active_screens_qs().only(*only_fields)

    if _model_has_field(DisplayScreen, "token"):
        screen = qs.filter(token__iexact=token_value).first()
        if screen:
            return _get_settings_by_school_id(screen.school_id)

    if _is_hex_sha256(token_value) and _model_has_field(DisplayScreen, "token"):
        for s in qs:
            try:
                if _sha256(s.token) == token_value:
                    return _get_settings_by_school_id(s.school_id)
            except Exception:
                continue

    return None


def _parse_hhmm(value: str | None) -> dt_time | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            return dt_time(hour=h, minute=m)
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            return dt_time(hour=h, minute=m, second=sec)
    except Exception:
        return None
    return None


def _infer_period_index(settings_obj: SchoolSettings, weekday: int, current_period: dict | None) -> int | None:
    if not current_period:
        return None

    idx = current_period.get("index")
    try:
        if idx is not None:
            idx_int = int(idx)
            if idx_int > 0:
                return idx_int
    except Exception:
        pass

    t_from = _parse_hhmm(current_period.get("from"))
    t_to = _parse_hhmm(current_period.get("to"))
    if not t_from or not t_to:
        return None

    try:
        return (
            Period.objects
            .filter(
                day__settings=settings_obj,
                day__weekday=weekday,
                starts_at=t_from,
                ends_at=t_to,
            )
            .values_list("index", flat=True)
            .first()
        )
    except Exception:
        return None


def _build_period_classes(settings_obj: SchoolSettings, weekday: int, period_index: int) -> list[dict]:
    qs = (
        ClassLesson.objects
        .filter(settings=settings_obj, weekday=weekday, period_index=period_index, is_active=True)
        .select_related("school_class", "subject", "teacher")
        .order_by("school_class__name")
    )
    items: list[dict] = []
    for cl in qs:
        items.append({
            "class": getattr(cl.school_class, "name", "") or "",
            "subject": getattr(cl.subject, "name", "") or "",
            "teacher": getattr(cl.teacher, "name", "") or "",
            "period_index": cl.period_index,
            "weekday": cl.weekday,
        })
    return items


def _normalize_theme_value(raw: str | None) -> str:
    """
    SchoolSettings.theme عندك: default/boys/girls
    شاشة العرض/CSS: indigo/emerald/rose
    """
    v = (raw or "").strip().lower()
    if not v:
        return "indigo"

    if v in ("indigo", "emerald", "rose", "cyan", "amber", "orange", "violet"):
        return v

    if v in ("default", "theme_default"):
        return "indigo"
    if v in ("boys", "theme_boys"):
        return "emerald"
    if v in ("girls", "theme_girls"):
        return "rose"

    return "indigo"


def _merge_real_data_into_snapshot(request, snap: dict, settings_obj: SchoolSettings):
    """
    ✅ دمج بيانات المدرسة الحقيقية داخل snapshot:
    - announcements  (notices.Announcement)
    - excellence     (notices.Excellence)
    - standby        (standby.StandbyAssignment)
    - duty           (schedule.DutyAssignment)
    """
    school = getattr(settings_obj, "school", None)
    if not school:
        return

    # -----------------------------
    # Announcements
    # -----------------------------
    try:
        from notices.models import Announcement  # type: ignore

        qs = Announcement.objects.active_for_school(school, now=timezone.now())

        order = []
        if _model_has_field(Announcement, "priority"):
            order.append("-priority")
        if _model_has_field(Announcement, "starts_at"):
            order.append("-starts_at")
        order.append("-id")
        qs = qs.order_by(*order)[:10]

        items = []
        for a in qs:
            d = a.as_dict() if hasattr(a, "as_dict") else {
                "title": getattr(a, "title", "") or "",
                "body": getattr(a, "body", "") or "",
                "level": getattr(a, "level", "") or "info",
            }
            title = (d.get("title") or "").strip()
            body = (d.get("body") or "").strip()
            if title and body:
                d["message"] = f"{title}\n{body}"
            else:
                d["message"] = title or body or "تنبيه"
            items.append(d)

        snap["announcements"] = items

    except Exception:
        logger.exception("snapshot: failed to merge announcements")

    # -----------------------------
    # Excellence (Honor Board)
    # -----------------------------
    try:
        from notices.models import Excellence  # type: ignore

        qs = Excellence.active_for_today(school) if hasattr(Excellence, "active_for_today") else Excellence.objects.filter(school=school)
        qs = qs[:30]

        items = []
        for e in qs:
            d = e.as_dict() if hasattr(e, "as_dict") else {
                "name": getattr(e, "teacher_name", "") or getattr(e, "name", "") or "",
                "reason": getattr(e, "reason", "") or "",
                "photo_url": getattr(e, "photo_url", None),
            }
            for k in ("image", "image_url", "photo_url"):
                if d.get(k):
                    d[k] = _abs_media_url(request, d.get(k))
            items.append(d)

        snap["excellence"] = items

    except Exception:
        logger.exception("snapshot: failed to merge excellence")

    # -----------------------------
    # Standby assignments
    # -----------------------------
    try:
        from standby.models import StandbyAssignment  # type: ignore

        today = timezone.localdate()
        qs = StandbyAssignment.objects.filter(school=school, date=today).order_by("period_index", "id")

        items = []
        for s in qs:
            items.append({
                "period_index": getattr(s, "period_index", None),
                "class_name": getattr(s, "class_name", "") or "",
                "teacher_name": getattr(s, "teacher_name", "") or "",
                "notes": getattr(s, "notes", "") or "",
            })

        snap["standby"] = items

    except Exception:
        logger.exception("snapshot: failed to merge standby")

    # -----------------------------
    # Duty / Supervision
    # -----------------------------
    try:
        from schedule.models import DutyAssignment  # type: ignore

        today = timezone.localdate()
        qs = (
            DutyAssignment.objects.filter(school=school, date=today, is_active=True)
            .order_by("priority", "-id")
        )

        snap["duty"] = {"items": [obj.as_dict() if hasattr(obj, "as_dict") else {
            "id": getattr(obj, "id", None),
            "date": getattr(obj, "date", None).isoformat() if getattr(obj, "date", None) else None,
            "teacher_name": getattr(obj, "teacher_name", "") or "",
            "duty_type": getattr(obj, "duty_type", "") or "",
            "duty_label": getattr(obj, "get_duty_type_display", lambda: "")() if hasattr(obj, "get_duty_type_display") else "",
            "location": getattr(obj, "location", "") or "",
        } for obj in qs]}

    except Exception:
        logger.exception("snapshot: failed to merge duty")


@require_GET
def ping(request):
    now = timezone.localtime()
    return JsonResponse({"ok": True, "now": now.isoformat()}, json_dumps_params={"ensure_ascii": False})


def _call_build_day_snapshot(settings_obj: SchoolSettings) -> dict:
    now = timezone.localtime()
    try:
        return build_day_snapshot(settings_obj, now=now)
    except TypeError:
        try:
            school = getattr(settings_obj, "school", None)
            if school:
                return build_day_snapshot(school=school, for_date=now.date())
        except Exception:
            pass
        return build_day_snapshot(settings_obj)


def _is_missing_index(d: dict) -> bool:
    if "index" not in d:
        return True
    v = d.get("index")
    return v is None or v == "" or v == 0

def _snapshot_cache_key(settings_obj: SchoolSettings) -> str:
    school_id = int(getattr(settings_obj, "school_id", None) or 0)
    rev = int(getattr(settings_obj, "schedule_revision", 0) or 0)
    return f"snapshot:v5:school:{school_id}:rev:{rev}"


def _snapshot_cache_ttl_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_CACHE_TTL", 15) or 15)
    except Exception:
        v = 15
    return max(5, min(30, v))


def _active_window_cache_ttl_seconds() -> int:
    """Cache TTL during active window (Phase 2).

    Defaults to 15–20s, but the upper bound can be raised via
    DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX when operating large fleets.
    """
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_ACTIVE_TTL", 15) or 15)
    except Exception:
        v = 15
    try:
        vmax = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX", 20) or 20)
    except Exception:
        vmax = 20
    vmax = max(15, min(60, vmax))
    out = max(15, min(vmax, v))
    if _safe_snapshot_rollout_enabled():
        try:
            safe_min = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_ACTIVE_TTL_SAFE_MIN", 30) or 30)
        except Exception:
            safe_min = 30
        safe_min = max(15, min(60, safe_min))
        out = max(out, safe_min)
    return out

def _steady_snapshot_cache_ttl_seconds(day_snap: dict) -> int:
    """Outside active window/holidays: long TTL, aligned to refresh_interval_sec when available."""
    try:
        s = (day_snap.get("settings") or {}) if isinstance(day_snap, dict) else {}
        refresh = int(s.get("refresh_interval_sec") or 3600)
    except Exception:
        refresh = 3600
    # Safe cap at 10 minutes (600s) to allow schedule changes to reflect faster
    try:
        max_ttl = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_STEADY_MAX_TTL", 600) or 600)
    except Exception:
        max_ttl = 600
    # Allow env to override up to 24h, but default logic caps at 600s (10m)
    max_ttl = max(300, min(86400, max_ttl))
    return max(300, min(max_ttl, refresh))

def _is_active_window(day_snap: dict) -> bool:
    try:
        meta = day_snap.get("meta") or {}
        return bool(meta.get("is_active_window"))
    except Exception:
        return False

def _steady_snapshot_cache_key(settings_obj: SchoolSettings, day_snap: dict) -> str:
    school_id = int(getattr(settings_obj, "school_id", None) or 0)
    rev = int(getattr(settings_obj, "schedule_revision", 0) or 0)
    # IMPORTANT: Use the same date source as read paths (timezone.localdate).
    # Previously we sometimes used day_snap['meta']['date'], which caused key mismatches
    # and steady_hit staying at 0 even when we wrote steady snapshots.
    date_str = str(timezone.localdate())
    return f"snapshot:v5:school:{school_id}:rev:{rev}:steady:{date_str}"


def get_cache_key(token_hash: str, school_id: int | None = None) -> str:
    """Tenant-safe snapshot cache key.

    If tokens are globally unique, token_hash alone is enough.
    We still include school_id whenever we have it, to avoid accidental collisions.
    """
    if school_id:
        return f"display:snapshot:{int(school_id)}:{token_hash}"
    return f"display:snapshot:{token_hash}"


def get_cache_key_rev(token_hash: str, school_id: int, schedule_revision: int) -> str:
    return f"display:snapshot:{int(school_id)}:rev:{int(schedule_revision)}:{token_hash}"


def compute_dynamic_ttl_seconds(day_snap: dict) -> int:
    if _is_active_window(day_snap):
        return _active_window_cache_ttl_seconds()
    return _steady_snapshot_cache_ttl_seconds(day_snap)


def _clamp_active_ttl_by_remaining_seconds(snap: dict, ttl: int) -> int:
    """Avoid caching a countdown snapshot past its natural boundary.

    If we cache a snapshot for (say) 15–20s while a period/break has 3s remaining,
    clients can keep receiving the *previous* block even after time has passed.
    That is especially problematic with status-first polling (revision may not change).
    """
    try:
        if not isinstance(snap, dict):
            return ttl
        st = snap.get("state") or {}
        st_type = str(st.get("type") or "").strip().lower()
        if st_type not in ("period", "break", "before"):
            return ttl
        rem = st.get("remaining_seconds")
        if isinstance(rem, (int, float)):
            r = int(rem)
            if r < 1:
                r = 1
            return max(1, min(int(ttl), r))
    except Exception:
        return ttl
    return ttl


def build_steady_snapshot(
    request,
    settings_obj: SchoolSettings,
    *,
    steady_state: str,
    refresh_interval_sec: int,
    label: str,
) -> dict:
    """Build a UI-safe steady snapshot (no expensive merges/queries).

    Required invariants:
    - never returns {}
    - includes expected arrays/keys
    - explicit state types for off-hours / no schedule
    """
    now = timezone.localtime()
    school = getattr(settings_obj, "school", None)

    school_name = ""
    if school is not None:
        school_name = getattr(school, "name", "") or ""
    if not school_name:
        school_name = getattr(settings_obj, "name", "") or ""

    logo = getattr(settings_obj, "logo_url", None)
    if not logo and school is not None:
        for attr in ("logo_url", "logo", "logo_image", "logo_file"):
            if hasattr(school, attr):
                val = getattr(school, attr)
                try:
                    logo = val.url
                except Exception:
                    logo = val
                if logo:
                    break

    return {
        "now": now.isoformat(),
        "meta": {
            "date": str(now.date()),
            "weekday": (now.date().weekday() + 1),
            "is_school_day": steady_state != "NO_SCHEDULE_TODAY",
            "is_active_window": False,
            "active_window": None,
        },
        "settings": {
            "name": school_name,
            "logo_url": _abs_media_url(request, logo),
            "theme": _normalize_theme_value(getattr(settings_obj, "theme", None)),
            "refresh_interval_sec": int(refresh_interval_sec),
            "standby_scroll_speed": float(getattr(settings_obj, "standby_scroll_speed", 0.8) or 0.8),
            "periods_scroll_speed": float(getattr(settings_obj, "periods_scroll_speed", 0.5) or 0.5),
        },
        "state": {
            "type": steady_state,
            "label": label,
            "from": None,
            "to": None,
            "remaining_seconds": 0,
        },
        "day_path": [],
        "current_period": None,
        "next_period": None,
        "period_classes": [],
        "standby": [],
        "excellence": [],
        "duty": {"items": []},
        "announcements": [],
    }


def _snapshot_edge_cache_max_age_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_EDGE_MAX_AGE", 10) or 10)
    except Exception:
        v = 10
    return max(1, min(60, v))

def _build_final_snapshot(
    request,
    settings_obj: SchoolSettings,
    *,
    day_snap: dict | None = None,
    merge_real_data: bool = True,
) -> dict:
    snap = day_snap if isinstance(day_snap, dict) else _call_build_day_snapshot(settings_obj)
    snap = _normalize_snapshot_keys(snap)

    # مفاتيح أساسية
    snap.setdefault("meta", {})
    snap.setdefault("settings", {})
    snap.setdefault("state", {})
    snap.setdefault("day_path", [])
    snap.setdefault("current_period", None)
    snap.setdefault("next_period", None)
    snap.setdefault("period_classes", [])
    snap.setdefault("standby", [])
    snap.setdefault("excellence", [])
    snap.setdefault("duty", {"items": []})
    snap.setdefault("announcements", [])

    # settings unify + theme mapping
    s = snap["settings"] or {}
    school = getattr(settings_obj, "school", None)

    school_name = ""
    if school is not None:
        school_name = getattr(school, "name", "") or ""
    if not school_name:
        school_name = getattr(settings_obj, "name", "") or ""

    if school_name and not s.get("name"):
        s["name"] = school_name

    logo = s.get("logo_url") or getattr(settings_obj, "logo_url", None)
    if not logo and school is not None:
        for attr in ("logo_url", "logo", "logo_image", "logo_file"):
            if hasattr(school, attr):
                val = getattr(school, attr)
                try:
                    logo = val.url
                except Exception:
                    logo = val
                if logo:
                    break
    s["logo_url"] = _abs_media_url(request, logo)

    # ✅ الثيم: تحويل default/boys/girls -> indigo/emerald/rose
    s["theme"] = _normalize_theme_value(getattr(settings_obj, "theme", None) or s.get("theme"))

    # ✅ Featured panel toggle (excellence|duty)
    s.setdefault("featured_panel", getattr(settings_obj, "featured_panel", "excellence") or "excellence")

    s.setdefault("refresh_interval_sec", getattr(settings_obj, "refresh_interval_sec", 10) or 10)
    s.setdefault("standby_scroll_speed", getattr(settings_obj, "standby_scroll_speed", 0.8) or 0.8)
    s.setdefault("periods_scroll_speed", getattr(settings_obj, "periods_scroll_speed", 0.5) or 0.5)

    # ✅ لون شاشة العرض (اختياري)
    accent = getattr(settings_obj, "display_accent_color", None) or s.get("display_accent_color")
    if isinstance(accent, str):
        accent = accent.strip()
    else:
        accent = None
    if accent and not re.match(r"^#[0-9A-Fa-f]{6}$", accent):
        accent = None
    s["display_accent_color"] = accent
    snap["settings"] = s

    # ✅ ROOT FIX: merge real data
    if merge_real_data:
        # ✅ ROOT FIX: merge real data
        _merge_real_data_into_snapshot(request, snap, settings_obj)

    # ✅ لو period_classes فاضية — نعبيها من ClassLesson
    if merge_real_data:
        # ✅ لو period_classes فاضية — نعبيها من ClassLesson
        try:
            current = snap.get("current_period") or {}
            kind = None
            if isinstance(current, dict):
                kind = current.get("kind") or current.get("type")
            if not kind:
                kind = (snap.get("state") or {}).get("type")

            if kind == "period" and not snap.get("period_classes"):
                meta = snap.get("meta") or {}
                weekday_raw = meta.get("weekday")
                try:
                    weekday = int(weekday_raw) if weekday_raw not in (None, "") else (timezone.localdate().weekday() + 1)
                except Exception:
                    weekday = timezone.localdate().weekday() + 1
                period_index = _infer_period_index(settings_obj, weekday, current if isinstance(current, dict) else None)
                if period_index:
                    snap["period_classes"] = _build_period_classes(settings_obj, weekday, period_index)
                    if isinstance(snap.get("current_period"), dict) and _is_missing_index(snap["current_period"]):
                        snap["current_period"]["index"] = period_index
        except Exception:
            logger.exception("snapshot: failed to fill period_classes")

        # ✅ ضمان ظهور رقم الحصة للـ current و next
        try:
            meta = snap.get("meta") or {}
            weekday_raw = meta.get("weekday")
            try:
                weekday = int(weekday_raw) if weekday_raw not in (None, "") else (timezone.localdate().weekday() + 1)
            except Exception:
                weekday = timezone.localdate().weekday() + 1

            curp = snap.get("current_period")
            if isinstance(curp, dict) and _is_missing_index(curp):
                idx = _infer_period_index(settings_obj, weekday, curp)
                if idx:
                    curp["index"] = idx

            nxtp = snap.get("next_period")
            if isinstance(nxtp, dict) and _is_missing_index(nxtp):
                idx2 = _infer_period_index(settings_obj, weekday, nxtp)
                if idx2:
                    nxtp["index"] = idx2
        except Exception:
            logger.exception("snapshot: failed to ensure current/next period index")

    return snap


@require_http_methods(["GET", "HEAD"])
def snapshot(request, token: str | None = None):
    """
    GET /api/display/snapshot/
    GET /api/display/snapshot/<token>/
    """
    try:
        # IMPORTANT (Production): do not allow query params to defeat caching.
        # Some screens may accidentally run with `?debug=1` / `?nocache=1` and spam the server.
        # We only honor nocache while developing locally (DEBUG=True).
        force_nocache = bool(dj_settings.DEBUG) and (request.GET.get("nocache") or "").strip().lower() in {"1", "true", "yes"}

        # Production-safe transition refresh: used at countdown==0.
        # Unlike nocache, this is allowed in production but is guarded by device binding + per-device rate limit.
        transition_requested = (request.GET.get("transition") or "").strip().lower() in {"1", "true", "yes"}
        transition_allowed = False

        # Diagnostics (off by default): enable extra cache logs to validate cache hit/miss behavior.
        cache_debug = (os.getenv("DISPLAY_SNAPSHOT_CACHE_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"})

        # Log cache env (sanitized) once per request when debug is enabled.
        if cache_debug and (getattr(request, "_cache_env_logged", False) is False):
            _log_cache_env(logger)
            try:
                setattr(request, "_cache_env_logged", True)
            except Exception:
                pass

        path = getattr(request, "path", "") or ""
        is_snapshot_path = path.startswith("/api/display/snapshot/")

        app_rev = _app_revision()

        def _apply_success_cache_headers(resp, snap: dict | None):
            """Allow short edge caching (Cloudflare) while avoiding browser caching.

            We only apply this to successful responses; errors keep no-store.
            Edge TTL is clamped by DISPLAY_SNAPSHOT_EDGE_MAX_AGE and snapshot TTL.
            """
            try:
                status = int(getattr(resp, "status_code", 0) or 0)
                if status not in (200, 304):
                    return resp
                if not isinstance(snap, dict):
                    return resp

                edge_cap = _snapshot_edge_cache_max_age_seconds()
                ttl = compute_dynamic_ttl_seconds(snap)
                ttl = _clamp_active_ttl_by_remaining_seconds(snap, ttl)
                edge_ttl = max(1, min(int(edge_cap), int(ttl)))

                # Browser: effectively bypass (must revalidate). Edge: allow small cache.
                resp["Cache-Control"] = f"public, max-age=0, must-revalidate, s-maxage={edge_ttl}"
            except Exception:
                pass
            return resp

        def _finalize(resp, *, cache_status: str, device_bound: bool | None = None, school_id: int | None = None, rev: int | None = None):
            if not resp.get("Cache-Control"):
                resp["Cache-Control"] = "no-store"
            # Keep compression negotiation; never vary on Cookie.
            resp["Vary"] = "Accept-Encoding"
            resp["X-Snapshot-Cache"] = cache_status
            if transition_allowed:
                resp["X-Snapshot-Transition"] = "1"
            # Always include a server clock hint (milliseconds since epoch).
            # This is intentionally in headers so it does not invalidate ETags or cached bodies.
            try:
                resp["X-Server-Time-MS"] = str(int(time.time() * 1000))
            except Exception:
                pass
            if device_bound is not None:
                resp["X-Snapshot-Device-Bound"] = "1" if device_bound else "0"
            if app_rev:
                resp["X-App-Revision"] = app_rev

            try:
                logger.info(
                    "snapshot_resp school_id=%s rev=%s status=%s cache=%s",
                    school_id,
                    rev,
                    int(getattr(resp, "status_code", 0) or 0),
                    cache_status,
                )
            except Exception:
                pass
            return resp

        token_value = _extract_token(request, token)
        if not token_value:
            resp = JsonResponse(
                _fallback_payload("رمز الدخول غير صحيح"),
                json_dumps_params={"ensure_ascii": False},
                status=403,
            )
            return _finalize(resp, cache_status="ERROR", device_bound=False if is_snapshot_path else None, school_id=None, rev=None)

        token_hash = _sha256(token_value)

        # ------------------------------------------------------------------
        # Phase 3 (School-level cache + lock):
        # Try to serve from a shared per-school snapshot cache before touching DB.
        # Keyed by (school_id, schedule_revision, local_day).
        # ------------------------------------------------------------------
        SCHOOL_SNAPSHOT_TTL = int(getattr(dj_settings, "SCHOOL_SNAPSHOT_TTL", 1200) or 1200)
        SCHOOL_LOCK_TTL = int(getattr(dj_settings, "SCHOOL_SNAPSHOT_LOCK_TTL", 8) or 8)
        SCHOOL_WAIT_TIMEOUT = float(getattr(dj_settings, "SCHOOL_SNAPSHOT_WAIT_TIMEOUT", 0.7) or 0.7)
        # Safety clamps
        SCHOOL_SNAPSHOT_TTL = max(60, min(3600, SCHOOL_SNAPSHOT_TTL))
        SCHOOL_LOCK_TTL = max(3, min(30, SCHOOL_LOCK_TTL))
        SCHOOL_WAIT_TIMEOUT = max(0.1, min(2.0, SCHOOL_WAIT_TIMEOUT))

        school_id_fast: int | None = None
        rev_fast: int | None = None
        day_key_fast: str | None = None
        school_snap_key_fast: str | None = None
        school_lock_key_fast: str | None = None

        try:
            from display.cache_utils import keys as display_keys, cache_add_lock, cache_wait_for
            from display.services import get_school_id_by_token, get_day_key
        except Exception:
            display_keys = None
            cache_add_lock = None
            cache_wait_for = None
            get_school_id_by_token = None
            get_day_key = None

        # === ANTI-LOOP GUARD (ISSUE #4) ===
        # If a token is looping (>30 req/min), force a long sleep without erroring.
        if not _snapshot_anti_loop_check(token_hash):
            if dj_settings.DEBUG:
                logger.warning("Anti-loop triggered for token_hash=%s", token_hash[:8])
            
            # Return valid (but empty/safe) payload with long refresh
            payload = _fallback_payload("التحديث متوقف مؤقتًا (حماية النظام)")
            payload["settings"]["refresh_interval_sec"] = 3600
            
            resp = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
            return _finalize(resp, cache_status="LOOP", device_bound=True if is_snapshot_path else None)
        # ==================================

        device_key = ""
        if is_snapshot_path:
            # Device binding without cookies: bind token -> device_key (header or query)
            device_key = (request.headers.get("X-Display-Device") or "").strip()
            if not device_key:
                device_key = (request.GET.get("dk") or request.GET.get("device_key") or "").strip()

            if not device_key:
                resp = JsonResponse({"detail": "device_required"}, status=403)
                return _finalize(resp, cache_status="ERROR", device_bound=False, school_id=None, rev=None)

            device_hash = _sha256(device_key)

            # Enable transition refresh only for bound devices, and rate-limit it.
            if transition_requested:
                try:
                    # Allow at most ~1 transition-bypass every ~12s per token+device.
                    # This keeps it safe even if the client retries.
                    tr_key = f"rl:snapshot_transition:{token_hash[:12]}:{device_hash[:12]}"
                    transition_allowed = bool(cache.add(tr_key, "1", timeout=12))
                except Exception:
                    transition_allowed = True

            # Rate limit: 1 req/sec per token+device with burst 3
            if not _snapshot_rate_limit_allow(token_hash, device_hash):
                resp = JsonResponse({"detail": "rate_limited"}, status=429)
                return _finalize(resp, cache_status="MISS", device_bound=True, school_id=None, rev=None)

            # Device binding (atomic, DRY helper shared with WebSocket)
            try:
                from display.services import (
                    ScreenBoundError,
                    ScreenNotFoundError,
                    bind_device_atomic,
                )
                
                screen = bind_device_atomic(
                    token=token_value,
                    device_id=device_key
                )
                # Successfully bound (or already bound to this device)
            except ScreenNotFoundError:
                resp = JsonResponse(
                    {
                        "detail": "token_invalid",
                        "message": "رمز الدخول غير صحيح أو غير نشط",
                    },
                    status=403,
                )
                return _finalize(resp, cache_status="ERROR", device_bound=False, school_id=None, rev=None)
            except ScreenBoundError as e:
                # Screen already bound to different device
                logger.warning(
                    "device_binding_reject token_hash=%s device=%s reason=%s",
                    token_hash[:12],
                    device_key[:8],
                    str(e)
                )
                resp = JsonResponse(
                    {
                        "detail": "screen_bound",
                        "message": str(e),
                    },
                    status=403,
                )
                return _finalize(resp, cache_status="ERROR", device_bound=True, school_id=None, rev=None)
            except Exception as e:
                logger.exception(f"Device binding error token_hash={token_hash[:12]}: {e}")
                resp = JsonResponse({"detail": "internal_error"}, status=500)
                return _finalize(resp, cache_status="ERROR", device_bound=False, school_id=None, rev=None)

        # Phase 2: token cache (tenant-safe when school_id known)
        cache_key = get_cache_key(token_hash)

        # During transition refreshes we must bypass token-level cache reads,
        # otherwise the client can keep seeing an old cached payload across a boundary.
        cached_entry = None if (force_nocache or transition_allowed) else cache.get(cache_key)
        if isinstance(cached_entry, dict) and isinstance(cached_entry.get("snap"), dict) and isinstance(cached_entry.get("etag"), str):
            school_id_for_log = None
            # If schedule revision changed, do not allow cached 304/old payload.
            try:
                cached_map = cache.get(f"display:token_map:{token_hash}")
                school_id_for_rev = None
                if isinstance(cached_map, dict):
                    school_id_for_rev = cached_map.get("school_id")
                else:
                    try:
                        school_id_for_rev = int(cached_map) if cached_map else None
                    except Exception:
                        school_id_for_rev = None

                school_id_for_log = school_id_for_rev

                if school_id_for_rev:
                    current_rev = _get_schedule_revision_for_school_id(int(school_id_for_rev))
                    cached_rev = cached_entry.get("rev")
                    if cached_rev is not None and int(cached_rev) != int(current_rev):
                        cached_entry = None
            except Exception:
                pass

        if isinstance(cached_entry, dict) and isinstance(cached_entry.get("snap"), dict) and isinstance(cached_entry.get("etag"), str):
            _metrics_incr("metrics:snapshot_cache:token_hit")
            _metrics_log_maybe()
            inm = _parse_if_none_match(request.headers.get("If-None-Match"))
            if inm and inm == cached_entry.get("etag"):
                resp = HttpResponseNotModified()
                resp["ETag"] = f"\"{cached_entry['etag']}\""
                _apply_success_cache_headers(resp, cached_entry.get("snap"))
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id_for_log, rev=cached_entry.get("rev"))
            resp = JsonResponse(cached_entry["snap"], json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{cached_entry['etag']}\""
            _apply_success_cache_headers(resp, cached_entry.get("snap"))
            return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id_for_log, rev=cached_entry.get("rev"))

        _metrics_incr("metrics:snapshot_cache:token_miss")
        _metrics_log_maybe()

        # School-level shared snapshot cache (order):
        # token->school (cache first) -> snap_key -> wait_for -> lock -> build
        if not force_nocache and display_keys is not None and get_school_id_by_token is not None:
            try:
                school_id_fast = get_school_id_by_token(token_value)
            except Exception:
                school_id_fast = None

            if school_id_fast:
                rev_fast = None
                day_key_fast = None
                try:
                    rev_fast = _get_schedule_revision_for_school_id(int(school_id_fast))
                    day_key_fast = get_day_key() if get_day_key is not None else timezone.localdate().strftime("%Y%m%d")
                    if transition_allowed and hasattr(display_keys, "snapshot_transition"):
                        school_snap_key_fast = display_keys.snapshot_transition(int(school_id_fast), int(rev_fast), str(day_key_fast))
                    else:
                        school_snap_key_fast = display_keys.snapshot(int(school_id_fast), int(rev_fast), str(day_key_fast))
                except Exception:
                    school_snap_key_fast = None

                if cache_debug:
                    try:
                        logger.info(
                            "school_snapshot_inputs school_id=%s rev=%s day_key=%s",
                            int(school_id_fast),
                            int(rev_fast) if rev_fast is not None else None,
                            str(day_key_fast) if day_key_fast is not None else None,
                        )
                    except Exception:
                        pass

            if school_id_fast and school_snap_key_fast:
                try:
                    cached_school_blob = cache.get(school_snap_key_fast)
                except Exception:
                    cached_school_blob = None

                if cached_school_blob is not None:
                    _metrics_incr("metrics:snapshot_cache:school_hit")
                    _metrics_log_maybe()
                    try:
                        logger.info("school_snapshot_get key=%s hit=1", school_snap_key_fast)
                    except Exception:
                        pass

                    try:
                        if isinstance(cached_school_blob, dict):
                            snap_fast = cached_school_blob
                            json_bytes_fast = _stable_json_bytes(snap_fast)
                        elif isinstance(cached_school_blob, (bytes, bytearray)):
                            json_bytes_fast = bytes(cached_school_blob)
                            snap_fast = json.loads(json_bytes_fast.decode("utf-8"))
                        else:
                            json_str = str(cached_school_blob)
                            json_bytes_fast = json_str.encode("utf-8")
                            snap_fast = json.loads(json_str)
                    except Exception:
                        snap_fast = None
                        json_bytes_fast = b""

                    if isinstance(snap_fast, dict):
                        etag_fast = _etag_from_json_bytes(json_bytes_fast) if json_bytes_fast else None
                        inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                        if etag_fast and inm and inm == etag_fast:
                            resp = HttpResponseNotModified()
                            resp["ETag"] = f"\"{etag_fast}\""
                            _apply_success_cache_headers(resp, snap_fast)
                            return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

                        resp = JsonResponse(snap_fast, json_dumps_params={"ensure_ascii": False})
                        if etag_fast:
                            resp["ETag"] = f"\"{etag_fast}\""
                        _apply_success_cache_headers(resp, snap_fast)
                        return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

                try:
                    logger.info("school_snapshot_get key=%s hit=0", school_snap_key_fast)
                except Exception:
                    pass

                # Wait briefly BEFORE any lock/build (most stampedes resolve here).
                if cache_wait_for is not None:
                    try:
                        waited0 = cache_wait_for(school_snap_key_fast, timeout_s=SCHOOL_WAIT_TIMEOUT, step_s=0.05)
                    except Exception:
                        waited0 = None

                    if waited0 is not None:
                        try:
                            if isinstance(waited0, dict):
                                snap_wait0 = waited0
                            elif isinstance(waited0, (bytes, bytearray)):
                                snap_wait0 = json.loads(bytes(waited0).decode("utf-8"))
                            else:
                                snap_wait0 = json.loads(str(waited0))
                        except Exception:
                            snap_wait0 = None

                        if isinstance(snap_wait0, dict):
                            _metrics_incr("metrics:snapshot_cache:school_hit")
                            _metrics_log_maybe()
                            resp = JsonResponse(snap_wait0, json_dumps_params={"ensure_ascii": False})
                            _apply_success_cache_headers(resp, snap_wait0)
                            return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

                # Now attempt lock.
                try:
                    school_lock_key_fast = display_keys.snapshot_lock(int(school_id_fast), int(rev_fast or 0), str(day_key_fast or ""))
                except Exception:
                    school_lock_key_fast = None

                got_lock = True
                if school_lock_key_fast and cache_add_lock is not None:
                    try:
                        got_lock = bool(cache_add_lock(school_lock_key_fast, ttl=SCHOOL_LOCK_TTL))
                    except Exception:
                        got_lock = True

                if not got_lock:
                    # One worker is building; wait once more, then return stale/fallback (200).
                    waited2 = None
                    if cache_wait_for is not None:
                        try:
                            waited2 = cache_wait_for(school_snap_key_fast, timeout_s=SCHOOL_WAIT_TIMEOUT, step_s=0.05)
                        except Exception:
                            waited2 = None

                    if waited2 is not None:
                        try:
                            if isinstance(waited2, dict):
                                snap_wait2 = waited2
                            elif isinstance(waited2, (bytes, bytearray)):
                                snap_wait2 = json.loads(bytes(waited2).decode("utf-8"))
                            else:
                                snap_wait2 = json.loads(str(waited2))
                        except Exception:
                            snap_wait2 = None

                        if isinstance(snap_wait2, dict):
                            _metrics_incr("metrics:snapshot_cache:school_hit")
                            _metrics_log_maybe()
                            resp = JsonResponse(snap_wait2, json_dumps_params={"ensure_ascii": False})
                            _apply_success_cache_headers(resp, snap_wait2)
                            return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

                    # Serve stale snapshot (last good) to avoid 202 retry storms.
                    try:
                        stale_key = display_keys.school_snapshot_stale(int(school_id_fast), str(day_key_fast))
                        stale_blob = cache.get(stale_key)
                    except Exception:
                        stale_blob = None

                    if stale_blob is not None:
                        try:
                            if isinstance(stale_blob, dict):
                                snap_stale = stale_blob
                            elif isinstance(stale_blob, (bytes, bytearray)):
                                snap_stale = json.loads(bytes(stale_blob).decode("utf-8"))
                            else:
                                snap_stale = json.loads(str(stale_blob))
                        except Exception:
                            snap_stale = None

                        if isinstance(snap_stale, dict):
                            resp = JsonResponse(snap_stale, json_dumps_params={"ensure_ascii": False})
                            _apply_success_cache_headers(resp, snap_stale)
                            return _finalize(resp, cache_status="STALE", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

                    resp = JsonResponse(
                        _fallback_building_payload(
                            school_id=int(school_id_fast),
                            rev=int(rev_fast or 0),
                            day_key=str(day_key_fast or ""),
                            reason="snapshot is being prepared",
                            refresh_interval_sec=3,
                        ),
                        json_dumps_params={"ensure_ascii": False},
                        status=200,
                    )
                    return _finalize(resp, cache_status="STALE", device_bound=True if is_snapshot_path else None, school_id=int(school_id_fast), rev=int(rev_fast) if rev_fast is not None else None)

        settings_obj = None
        hashed_token = token_hash
        cached_school_id = None

        # 0) ✅ Cache Hit: Check if token is already mapped to school_id
        if token_value and len(token_value) > 10:
            # Negative cache check
            neg_key = f"display:token_neg:{hashed_token}"
            if cache.get(neg_key):
                resp = JsonResponse(
                    _fallback_payload("رمز الدخول غير صحيح (cached)"),
                    json_dumps_params={"ensure_ascii": False},
                    status=403,
                )
                resp["Cache-Control"] = "no-store"
                return _finalize(resp, cache_status="ERROR", device_bound=True if is_snapshot_path else None)

            # Positive cache check
            map_key = f"display:token_map:{hashed_token}"
            cached_map = cache.get(map_key)
            if cached_map:
                if isinstance(cached_map, dict):
                    cached_school_id = cached_map.get("school_id")
                else:
                    # Legacy or simple integer fallback
                    try:
                        cached_school_id = int(cached_map)
                    except:
                        pass
        
        # 1) If we have school_id, try to fetch Snapshot directly from cache
        if cached_school_id and not force_nocache:
            # Bump cache version v1 -> v2 to invalidate old stuck "Off" states
            cached_rev = _get_schedule_revision_for_school_id(int(cached_school_id))
            # If we already have a rev-specific tenant cache entry, prefer it.
            # This is especially helpful during stampedes where we may have cached a short-lived
            # response under the tenant key but not yet populated the per-school key.
            try:
                tenant_key_early = get_cache_key_rev(token_hash, int(cached_school_id), int(cached_rev))
                cached_entry_early = cache.get(tenant_key_early)
                if isinstance(cached_entry_early, dict) and isinstance(cached_entry_early.get("snap"), dict) and isinstance(cached_entry_early.get("etag"), str):
                    _metrics_incr("metrics:snapshot_cache:token_hit")
                    _metrics_log_maybe()
                    inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                    if inm and inm == cached_entry_early.get("etag"):
                        resp = HttpResponseNotModified()
                        resp["ETag"] = f"\"{cached_entry_early['etag']}\""
                        _apply_success_cache_headers(resp, cached_entry_early.get("snap"))
                        return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))
                    resp = JsonResponse(cached_entry_early["snap"], json_dumps_params={"ensure_ascii": False})
                    resp["ETag"] = f"\"{cached_entry_early['etag']}\""
                    _apply_success_cache_headers(resp, cached_entry_early.get("snap"))
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))
            except Exception:
                pass
            snap_key = f"snapshot:v5:school:{cached_school_id}:rev:{int(cached_rev)}"
            cached_snap = cache.get(snap_key)
            if isinstance(cached_snap, dict):
                _metrics_incr("metrics:snapshot_cache:school_hit")
                _metrics_log_maybe()
                # We'll still go through token-keyed cache so ETag/304 and rate limit are consistent.
                try:
                    json_bytes = _stable_json_bytes(cached_snap)
                    etag = _etag_from_json_bytes(json_bytes)
                    token_timeout = _active_window_cache_ttl_seconds() if _is_active_window(cached_snap) else _steady_snapshot_cache_ttl_seconds(cached_snap)
                    token_timeout = _clamp_active_ttl_by_remaining_seconds(cached_snap, token_timeout)
                    tok_key = get_cache_key_rev(token_hash, int(cached_school_id), int(cached_rev))
                    cache.set(tok_key, {"snap": cached_snap, "etag": etag, "rev": int(cached_rev)}, timeout=token_timeout)
                    cache.set(get_cache_key(token_hash), {"snap": cached_snap, "etag": etag, "rev": int(cached_rev)}, timeout=token_timeout)
                except Exception:
                    etag = None

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if etag and inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_snap)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))

                resp = JsonResponse(cached_snap, json_dumps_params={"ensure_ascii": False})
                if etag:
                    resp["ETag"] = f"\"{etag}\""
                _apply_success_cache_headers(resp, cached_snap)
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))

            # steady snapshot fallback (long TTL outside window/holidays)
            # Bump cache version v2 -> v3
            steady_key = _steady_cache_key_for_school_rev(int(cached_school_id), int(cached_rev))
            cached_steady = cache.get(steady_key)
            _log_steady_get(steady_key, hit=isinstance(cached_steady, dict), school_id=int(cached_school_id), rev=int(cached_rev))
            if isinstance(cached_steady, dict):
                _metrics_incr("metrics:snapshot_cache:steady_hit")
                _metrics_log_maybe()
                try:
                    json_bytes = _stable_json_bytes(cached_steady)
                    etag = _etag_from_json_bytes(json_bytes)
                    token_timeout = _steady_snapshot_cache_ttl_seconds(cached_steady)
                    tok_key = get_cache_key_rev(token_hash, int(cached_school_id), int(cached_rev))
                    cache.set(tok_key, {"snap": cached_steady, "etag": etag, "rev": int(cached_rev)}, timeout=token_timeout)
                    cache.set(get_cache_key(token_hash), {"snap": cached_steady, "etag": etag, "rev": int(cached_rev)}, timeout=token_timeout)
                except Exception:
                    etag = None

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if etag and inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_steady)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))

                resp = JsonResponse(cached_steady, json_dumps_params={"ensure_ascii": False})
                if etag:
                    resp["ETag"] = f"\"{etag}\""
                _apply_success_cache_headers(resp, cached_steady)
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=int(cached_school_id), rev=int(cached_rev))

            _metrics_incr("metrics:snapshot_cache:school_miss")
            _metrics_incr("metrics:snapshot_cache:steady_miss")
            _metrics_log_maybe()

            # If snapshot missing, we need settings_obj to build it
            try:
                settings_obj = _get_settings_by_school_id(int(cached_school_id))
            except Exception:
                pass

        # 2) DisplayScreen (DB Lookup if not found yet)
        if not settings_obj:
            settings_obj = _match_settings_via_display_screen(token_value) if token_value else None

        # 3) fallback token search
        if not settings_obj and token_value:
            settings_obj = _get_settings_by_token(token_value)

        # 4) school_id param
        if not settings_obj:
            school_id_raw = (request.GET.get("school_id") or request.GET.get("school") or "").strip()
            if school_id_raw.isdigit():
                settings_obj = _get_settings_by_school_id(int(school_id_raw))

        # 5) single settings fallback
        if not settings_obj:
            # ✅ Negative Cache: Cache invalid token to prevent DB hammering
            if token_value and len(token_value) > 10:
                neg_key = f"display:token_neg:{hashed_token}"
                cache.set(neg_key, "1", timeout=60) # 60 seconds

            total = SchoolSettings.objects.count()
            if total == 1:
                settings_obj = SchoolSettings.objects.select_related("school").first()
            else:
                if dj_settings.DEBUG:
                    logger.warning(
                        "snapshot: no match. token=%s school_id=%s total_settings=%s",
                        (token_value[:10] + "...") if token_value else None,
                        request.GET.get("school_id") or request.GET.get("school"),
                        total,
                    )
                resp = JsonResponse(_fallback_payload("إعدادات المدرسة غير مهيأة"), json_dumps_params={"ensure_ascii": False})
                resp["Cache-Control"] = "no-store"
                return _finalize(resp, cache_status="ERROR", device_bound=True if is_snapshot_path else None, school_id=None, rev=None)
        
        # ✅ Cache Update: Store valid token mapping if not cached (24h)
        if token_value and settings_obj and len(token_value) > 10 and not cached_school_id:
            map_key = f"display:token_map:{hashed_token}"
            try:
                if getattr(settings_obj, 'school_id', None):
                   # Store dict compatible with middleware
                   payload = {"school_id": settings_obj.school_id}
                   # We don't have screen ID here easily unless we fetched via _match_settings_via_display_screen
                   # But middleware will update it with full details on next hit.
                   cache.set(map_key, payload, timeout=86400) # 24 hours
            except Exception:
                pass

        # 6) Phase 2: build snapshot once per school (stampede guard)
        school_id = int(getattr(settings_obj, "school_id", None) or 0)
        rev = int(getattr(settings_obj, "schedule_revision", 0) or 0)
        tenant_cache_key = get_cache_key_rev(token_hash, school_id, rev)
        if tenant_cache_key != cache_key:
            cached_entry2 = None if force_nocache else cache.get(tenant_cache_key)
            if isinstance(cached_entry2, dict) and isinstance(cached_entry2.get("snap"), dict) and isinstance(cached_entry2.get("etag"), str):
                try:
                    cached_rev2 = cached_entry2.get("rev")
                    if cached_rev2 is not None and int(cached_rev2) != int(rev):
                        cached_entry2 = None
                except Exception:
                    pass

            if isinstance(cached_entry2, dict) and isinstance(cached_entry2.get("snap"), dict) and isinstance(cached_entry2.get("etag"), str):
                _metrics_incr("metrics:snapshot_cache:token_hit")
                _metrics_log_maybe()
                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == cached_entry2.get("etag"):
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{cached_entry2['etag']}\""
                    _apply_success_cache_headers(resp, cached_entry2.get("snap"))
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)
                resp = JsonResponse(cached_entry2["snap"], json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{cached_entry2['etag']}\""
                _apply_success_cache_headers(resp, cached_entry2.get("snap"))
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)

        snap_key = _snapshot_cache_key(settings_obj)
        # IMPORTANT: steady cache must be checked before any build.
        steady_key = _steady_cache_key_for_school_rev(school_id, rev)

        if not force_nocache:
            cached_school = cache.get(snap_key)
            if isinstance(cached_school, dict):
                _metrics_incr("metrics:snapshot_cache:school_hit")
                _metrics_log_maybe()
                json_bytes = _stable_json_bytes(cached_school)
                etag = _etag_from_json_bytes(json_bytes)
                token_timeout = _active_window_cache_ttl_seconds() if _is_active_window(cached_school) else _steady_snapshot_cache_ttl_seconds(cached_school)
                token_timeout = _clamp_active_ttl_by_remaining_seconds(cached_school, token_timeout)
                try:
                    cache.set(tenant_cache_key, {"snap": cached_school, "etag": etag, "rev": int(rev)}, timeout=token_timeout)
                except Exception:
                    pass

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_school)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)
                resp = JsonResponse(cached_school, json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{etag}\""
                _apply_success_cache_headers(resp, cached_school)
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)

            cached_steady2 = cache.get(steady_key)
            _log_steady_get(steady_key, hit=isinstance(cached_steady2, dict), school_id=school_id, rev=rev)
            if isinstance(cached_steady2, dict):
                _metrics_incr("metrics:snapshot_cache:steady_hit")
                _metrics_log_maybe()
                json_bytes = _stable_json_bytes(cached_steady2)
                etag = _etag_from_json_bytes(json_bytes)
                token_timeout = _steady_snapshot_cache_ttl_seconds(cached_steady2)
                try:
                    cache.set(tenant_cache_key, {"snap": cached_steady2, "etag": etag, "rev": int(rev)}, timeout=token_timeout)
                except Exception:
                    pass

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_steady2)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)
                resp = JsonResponse(cached_steady2, json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{etag}\""
                _apply_success_cache_headers(resp, cached_steady2)
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)

        # Stampede lock: one build per school
        date_str = str(timezone.localdate())
        school_lock_key = f"lock:snapshot:v5:school:{school_id}:rev:{rev}:{date_str}"
        have_lock = True
        if not force_nocache:
            try:
                have_lock = bool(cache.add(school_lock_key, "1", timeout=_snapshot_build_lock_ttl_seconds()))
            except Exception:
                have_lock = True

        if not have_lock:
            # Another worker is building this school's snapshot.
            # ✅ IMPROVED: محاولة عرض snapshot قديم بدلاً من الانتظار أو شاشة فارغة
            
            # أولاً: محاولة الحصول على snapshot قديم من أي revision
            stale_snap = _get_stale_snapshot_fallback(school_id)
            if stale_snap:
                _metrics_incr("metrics:snapshot_cache:stale_fallback")
                _metrics_log_maybe()
                json_bytes = _stable_json_bytes(stale_snap)
                etag = _etag_from_json_bytes(json_bytes)
                resp = JsonResponse(stale_snap, json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{etag}\""
                resp["X-Cache-Status"] = "STALE-FALLBACK"
                _apply_success_cache_headers(resp, stale_snap)
                return _finalize(resp, cache_status="STALE", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)
            
            # ثانياً: الانتظار قليلاً لعل البناء ينتهي
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                cached_school = cache.get(snap_key)
                if isinstance(cached_school, dict):
                    json_bytes = _stable_json_bytes(cached_school)
                    etag = _etag_from_json_bytes(json_bytes)
                    try:
                        tmo = _active_window_cache_ttl_seconds()
                        tmo = _clamp_active_ttl_by_remaining_seconds(cached_school, tmo)
                        cache.set(tenant_cache_key, {"snap": cached_school, "etag": etag, "rev": int(rev)}, timeout=tmo)
                        cache.set(get_cache_key(token_hash), {"snap": cached_school, "etag": etag, "rev": int(rev)}, timeout=tmo)
                    except Exception:
                        pass
                    resp = JsonResponse(cached_school, json_dumps_params={"ensure_ascii": False})
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_school)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                cached_steady2 = cache.get(steady_key)
                if isinstance(cached_steady2, dict):
                    json_bytes = _stable_json_bytes(cached_steady2)
                    etag = _etag_from_json_bytes(json_bytes)
                    try:
                        tmo = _steady_snapshot_cache_ttl_seconds(cached_steady2)
                        cache.set(tenant_cache_key, {"snap": cached_steady2, "etag": etag, "rev": int(rev)}, timeout=tmo)
                        cache.set(get_cache_key(token_hash), {"snap": cached_steady2, "etag": etag, "rev": int(rev)}, timeout=tmo)
                    except Exception:
                        pass
                    resp = JsonResponse(cached_steady2, json_dumps_params={"ensure_ascii": False})
                    resp["ETag"] = f"\"{etag}\""
                    _apply_success_cache_headers(resp, cached_steady2)
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                time.sleep(0.05)

            # No stale available: return a short-lived steady snapshot to avoid stampede.
            tmp = build_steady_snapshot(
                request,
                settings_obj,
                steady_state="BUILDING",
                refresh_interval_sec=10,
                label="جاري تجهيز الجدول...",
            )
            json_bytes = _stable_json_bytes(tmp)
            etag = _etag_from_json_bytes(json_bytes)
            try:
                cache.set(tenant_cache_key, {"snap": tmp, "etag": etag, "rev": int(rev)}, timeout=5)
                cache.set(get_cache_key(token_hash), {"snap": tmp, "etag": etag, "rev": int(rev)}, timeout=5)
            except Exception:
                pass
            resp = JsonResponse(tmp, json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{etag}\""
            _apply_success_cache_headers(resp, tmp)
            return _finalize(resp, cache_status="STALE", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)

        try:
            t0 = time.monotonic()

            day_snap = _normalize_snapshot_keys(_call_build_day_snapshot(settings_obj))
            active_window = _is_active_window(day_snap)
            token_timeout = compute_dynamic_ttl_seconds(day_snap)

            # ✅ Always include schedule revision in meta so ETag changes even if today's JSON wouldn't.
            try:
                meta = day_snap.get("meta") if isinstance(day_snap, dict) else None
                if not isinstance(meta, dict):
                    meta = {}
                    if isinstance(day_snap, dict):
                        day_snap["meta"] = meta
                meta["schedule_revision"] = rev
                
                # Phase 2: WebSocket feature flag (Dark Launch)
                # Clients will only attempt WS if this flag is True
                ws_enabled = getattr(dj_settings, "DISPLAY_WS_ENABLED", False)
                meta["ws_enabled"] = bool(ws_enabled)
            except Exception:
                pass

            if active_window:
                snap = _build_final_snapshot(request, settings_obj, day_snap=day_snap, merge_real_data=True)
                # Add stable jitter to spread expirations across schools and reduce peak load.
                try:
                    ttl_max = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX", 20) or 20)
                except Exception:
                    ttl_max = 20
                ttl_max = max(15, min(60, ttl_max))
                token_timeout = _stable_ttl_with_jitter(
                    token_timeout,
                    seed=f"active:{school_id}:{rev}:{timezone.localdate()}",
                    ttl_max=ttl_max,
                )
                token_timeout = _clamp_active_ttl_by_remaining_seconds(snap, token_timeout)
                if not force_nocache:
                    try:
                        cache.set(_snapshot_cache_key(settings_obj), snap, timeout=token_timeout)
                    except Exception:
                        pass
            else:
                snap = _build_final_snapshot(request, settings_obj, day_snap=day_snap, merge_real_data=False)

                meta = day_snap.get("meta") or {}
                is_school_day = bool(meta.get("is_school_day"))
                st = (day_snap.get("state") or {}) if isinstance(day_snap, dict) else {}
                st_type = str(st.get("type") or "").strip().lower()

                # Outside active window we want to dramatically reduce polling.
                # We still keep a periodic check so screens can resume automatically.
                base_refresh = int((day_snap.get("settings") or {}).get("refresh_interval_sec") or 3600)
                if not is_school_day:
                    # Holidays / no schedule: hourly check is enough.
                    refresh = max(base_refresh, 3600)
                elif st_type == "before":
                    # Before school: check occasionally; countdown/UI runs client-side.
                    refresh = max(base_refresh, 60)
                else:
                    # After school / off-hours: slow down to reduce load.
                    refresh = max(base_refresh, 600)

                # Safety clamp (5s .. 24h)
                refresh = max(5, min(86400, int(refresh)))

                if not is_school_day:
                    snap["state"]["type"] = "NO_SCHEDULE_TODAY"
                    snap["state"]["label"] = "لا يوجد جدول اليوم"
                elif st_type == "before":
                    snap["state"]["type"] = "BEFORE_SCHOOL"
                    snap["state"]["label"] = "قبل بداية الدوام"
                else:
                    snap["state"]["type"] = "OFF_HOURS"
                    snap["state"]["label"] = "انتهى الدوام"

                try:
                    snap["settings"]["refresh_interval_sec"] = int(refresh)
                except Exception:
                    pass

                # Align token cache TTL to the chosen off-hours refresh interval.
                try:
                    token_timeout = _steady_snapshot_cache_ttl_seconds(snap)
                except Exception:
                    pass

                # Also write a short-lived school-level cache entry keyed only by (school_id, rev).
                # This increases hit-rate across devices/tokens while keeping staleness risk low.
                if not force_nocache:
                    try:
                        school_ttl = _snapshot_cache_ttl_seconds()
                        school_ttl = _clamp_active_ttl_by_remaining_seconds(snap, school_ttl)
                        cache.set(_snapshot_cache_key(settings_obj), snap, timeout=school_ttl)
                    except Exception:
                        pass

                if not force_nocache:
                    try:
                        steady_write_key = _steady_cache_key_for_school_rev(school_id, rev)
                        steady_ttl = _steady_snapshot_cache_ttl_seconds(snap)
                        cache.set(steady_write_key, snap, timeout=steady_ttl)
                        _log_steady_set(
                            steady_write_key,
                            ttl=int(steady_ttl),
                            school_id=school_id,
                            rev=rev,
                            success=True,
                        )
                    except Exception as e:
                        _log_steady_set(
                            _steady_cache_key_for_school_rev(school_id, rev),
                            ttl=int(_steady_snapshot_cache_ttl_seconds(snap)),
                            school_id=school_id,
                            rev=rev,
                            success=False,
                            error=e.__class__.__name__,
                        )

            build_ms = int((time.monotonic() - t0) * 1000)
            _metrics_incr("metrics:snapshot_cache:build_count")
            _metrics_add("metrics:snapshot_cache:build_sum_ms", build_ms)
            _metrics_set_max("metrics:snapshot_cache:build_max_ms", build_ms)
            _metrics_log_maybe()

            json_bytes = _stable_json_bytes(snap)
            etag = _etag_from_json_bytes(json_bytes)

            # Write shared per-school snapshot (JSON) for this day/rev.
            if not force_nocache and display_keys is not None:
                try:
                    # Prefer the fast-path identifiers (if computed), otherwise derive now.
                    sid = int(school_id_fast) if school_id_fast else int(school_id)
                    r = int(rev_fast) if rev_fast is not None else int(rev)
                    dk = str(day_key_fast) if day_key_fast else timezone.localdate().strftime("%Y%m%d")
                    blob = json.dumps(snap, ensure_ascii=False)

                    # Always write the normal per-school key used by regular polling.
                    k_normal = display_keys.snapshot(sid, r, dk)
                    cache.set(k_normal, blob, timeout=SCHOOL_SNAPSHOT_TTL)

                    # If this was a transition refresh, also write a short-lived transition key.
                    # This avoids returning an old long-TTL snapshot during the boundary window.
                    k_transition = None
                    if transition_allowed and hasattr(display_keys, "snapshot_transition"):
                        try:
                            k_transition = display_keys.snapshot_transition(sid, r, dk)
                            cache.set(k_transition, blob, timeout=min(30, int(SCHOOL_SNAPSHOT_TTL)))
                        except Exception:
                            k_transition = None

                    # Round-trip probe: verify cache.get can immediately read what we wrote.
                    if cache_debug:
                        try:
                            probe = cache.get(k_normal)
                            ok = bool(probe)
                        except Exception:
                            ok = False
                        try:
                            logger.info(
                                "school_snapshot_probe key=%s ok=%s backend=%s",
                                k_normal,
                                1 if ok else 0,
                                getattr(cache, "__class__", type(cache)).__name__,
                            )
                        except Exception:
                            pass

                    # Also write a rev-agnostic stale snapshot for the same school/day.
                    try:
                        stale_key = display_keys.school_snapshot_stale(sid, dk)
                        cache.set(stale_key, blob, timeout=60 * 60 * 6)  # 6 hours
                    except Exception:
                        pass

                    try:
                        logger.info("school_snapshot_set key=%s bytes=%s ttl=%s", k_normal, len(blob.encode("utf-8")), SCHOOL_SNAPSHOT_TTL)
                    except Exception:
                        pass

                    if k_transition:
                        try:
                            logger.info("school_snapshot_set_transition key=%s bytes=%s ttl=%s", k_transition, len(blob.encode("utf-8")), min(30, int(SCHOOL_SNAPSHOT_TTL)))
                        except Exception:
                            pass
                except Exception:
                    pass

            try:
                logger.info(
                    "snapshot_build school_id=%s rev=%s size_bytes=%s build_ms=%s",
                    int(school_id),
                    int(rev),
                    int(len(json_bytes)),
                    int(build_ms),
                )
            except Exception:
                pass

            if not force_nocache:
                try:
                    token_timeout = _clamp_active_ttl_by_remaining_seconds(snap, token_timeout)
                    cache.set(tenant_cache_key, {"snap": snap, "etag": etag, "rev": rev}, timeout=token_timeout)
                    cache.set(get_cache_key(token_hash), {"snap": snap, "etag": etag, "rev": rev}, timeout=token_timeout)
                except Exception:
                    pass

            inm = _parse_if_none_match(request.headers.get("If-None-Match"))
            if inm and inm == etag:
                resp = HttpResponseNotModified()
                resp["ETag"] = f"\"{etag}\""
                _apply_success_cache_headers(resp, snap)
                return _finalize(resp, cache_status="MISS" if force_nocache else "MISS", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)

            resp = JsonResponse(snap, json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{etag}\""
            _apply_success_cache_headers(resp, snap)
            return _finalize(resp, cache_status="BYPASS" if force_nocache else "MISS", device_bound=True if is_snapshot_path else None, school_id=school_id, rev=rev)
        finally:
            if not force_nocache:
                try:
                    cache.delete(school_lock_key)
                except Exception:
                    pass

            # Release Phase 3 lock (best-effort).
            if school_lock_key_fast and not force_nocache:
                try:
                    cache.delete(school_lock_key_fast)
                except Exception:
                    pass

    except Exception as e:
        logger.exception("snapshot error: %s", e)
        resp = JsonResponse(_fallback_payload("حدث خطأ أثناء جلب البيانات"), json_dumps_params={"ensure_ascii": False})
        resp["Cache-Control"] = "no-store"
        resp["Vary"] = "Accept-Encoding"
        resp["X-Snapshot-Cache"] = "ERROR"
        if app_rev:
            resp["X-App-Revision"] = app_rev
        return resp
