from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from typing import Any

from django.conf import settings
from django.core.cache import cache
from display.cache_utils import normalize_day_key


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "true" if default else "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _env_int(name: str, default: int, *, min_v: int, max_v: int) -> int:
    try:
        value = int(os.getenv(name, str(default)).strip() or default)
    except Exception:
        value = int(default)
    return max(min_v, min(max_v, value))


def _env_float(name: str, default: float, *, min_v: float, max_v: float) -> float:
    try:
        value = float(os.getenv(name, str(default)).strip() or default)
    except Exception:
        value = float(default)
    return max(min_v, min(max_v, value))


def _metrics_incr(key: str) -> None:
    try:
        cache.incr(key)
    except Exception:
        try:
            cache.add(key, 0, timeout=60 * 60 * 24)
            cache.incr(key)
        except Exception:
            try:
                cur = int(cache.get(key) or 0)
                cache.set(key, cur + 1, timeout=60 * 60 * 24)
            except Exception:
                pass


def _metrics_add(key: str, delta: int) -> None:
    try:
        cache.incr(key, int(delta))
    except Exception:
        try:
            cur = int(cache.get(key) or 0)
            cache.set(key, cur + int(delta), timeout=60 * 60 * 24)
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


def snapshot_async_build_enabled() -> bool:
    return bool(getattr(settings, "DISPLAY_SNAPSHOT_ASYNC_BUILD", _env_bool("DISPLAY_SNAPSHOT_ASYNC_BUILD", True)))


def snapshot_inline_fallback_enabled() -> bool:
    return bool(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_INLINE_FALLBACK",
            _env_bool("DISPLAY_SNAPSHOT_INLINE_FALLBACK", True),
        )
    )


def _queue_name() -> str:
    return str(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_QUEUE_NAME",
            os.getenv("DISPLAY_SNAPSHOT_QUEUE_NAME", "display:snapshot:build:queue"),
        )
        or "display:snapshot:build:queue"
    ).strip()


def _job_dedupe_ttl_seconds() -> int:
    return int(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_JOB_DEDUPE_TTL",
            _env_int("DISPLAY_SNAPSHOT_JOB_DEDUPE_TTL", 30, min_v=5, max_v=300),
        )
        or 30
    )


def _enqueue_debounce_seconds() -> int:
    return int(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_REBUILD_DEBOUNCE_SEC",
            _env_int("DISPLAY_SNAPSHOT_REBUILD_DEBOUNCE_SEC", 3, min_v=2, max_v=5),
        )
        or 3
    )


def _require_worker_alive_for_enqueue() -> bool:
    return bool(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_REQUIRE_WORKER_ALIVE",
            _env_bool("DISPLAY_SNAPSHOT_REQUIRE_WORKER_ALIVE", True),
        )
    )


def worker_heartbeat_ttl_seconds() -> int:
    return int(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_WORKER_HEARTBEAT_TTL",
            _env_int("DISPLAY_SNAPSHOT_WORKER_HEARTBEAT_TTL", 45, min_v=10, max_v=300),
        )
        or 45
    )


def queue_wait_timeout_seconds() -> float:
    return float(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_QUEUE_WAIT_TIMEOUT",
            _env_float("DISPLAY_SNAPSHOT_QUEUE_WAIT_TIMEOUT", 0.35, min_v=0.0, max_v=2.0),
        )
        or 0.35
    )


def _worker_heartbeat_key() -> str:
    return "display:snapshot:worker:heartbeat"


def _job_dedupe_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:job:{int(school_id)}:{normalize_day_key(day_key)}"


def _enqueue_debounce_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:enqueue:debounce:{int(school_id)}:{normalize_day_key(day_key)}"


def _get_cache_redis_connection():
    try:
        from django_redis import get_redis_connection  # type: ignore

        return get_redis_connection("default")
    except Exception:
        return None


def snapshot_queue_available() -> bool:
    try:
        cfg = getattr(settings, "CACHES", {}).get("default", {}) or {}
        backend = str(cfg.get("BACKEND", "") or "").lower()
        return "django_redis" in backend or "rediscache" in backend
    except Exception:
        return False


def touch_snapshot_worker_heartbeat(*, worker_id: str | None = None) -> dict[str, Any]:
    payload = {
        "ts": time.time(),
        "worker_id": (worker_id or f"{socket.gethostname()}:{os.getpid()}"),
    }
    try:
        cache.set(_worker_heartbeat_key(), payload, timeout=worker_heartbeat_ttl_seconds())
    except Exception:
        pass
    return payload


def snapshot_worker_status() -> dict[str, Any]:
    hb = None
    try:
        hb = cache.get(_worker_heartbeat_key())
    except Exception:
        hb = None

    now = time.time()
    ts = 0.0
    worker_id = ""
    if isinstance(hb, dict):
        try:
            ts = float(hb.get("ts") or 0.0)
        except Exception:
            ts = 0.0
        worker_id = str(hb.get("worker_id") or "")
    age_sec = max(0.0, now - ts) if ts > 0 else None
    alive = bool(age_sec is not None and age_sec <= float(worker_heartbeat_ttl_seconds()))

    queue_depth = None
    conn = _get_cache_redis_connection()
    if conn is not None:
        try:
            queue_depth = int(conn.llen(_queue_name()) or 0)
        except Exception:
            queue_depth = None

    return {
        "alive": alive,
        "age_sec": round(age_sec, 3) if age_sec is not None else None,
        "worker_id": worker_id or None,
        "queue_available": snapshot_queue_available(),
        "queue_depth": queue_depth,
    }


def enqueue_snapshot_build(*, school_id: int, rev: int, day_key: str, reason: str = "request_miss") -> dict[str, Any]:
    school_id = int(school_id or 0)
    rev = int(rev or 0)
    day_key = normalize_day_key(day_key)
    if not school_id or not day_key:
        return {"queued": False, "reason": "invalid_payload"}
    if not snapshot_async_build_enabled():
        return {"queued": False, "reason": "async_disabled"}
    if not snapshot_queue_available():
        return {"queued": False, "reason": "queue_unavailable"}

    if _require_worker_alive_for_enqueue():
        try:
            worker_alive = bool(snapshot_worker_status().get("alive"))
        except Exception:
            worker_alive = False
        if not worker_alive:
            _metrics_incr("metrics:snapshot_queue:worker_unavailable")
            return {"queued": False, "reason": "worker_unavailable"}

    conn = _get_cache_redis_connection()
    if conn is None:
        return {"queued": False, "reason": "redis_unavailable"}

    debounce_key = _enqueue_debounce_key(school_id, day_key)
    try:
        if not bool(cache.add(debounce_key, str(rev), timeout=_enqueue_debounce_seconds())):
            _metrics_incr("metrics:snapshot_queue:debounced")
            return {"queued": False, "debounced": True, "debounce_key": debounce_key}
    except Exception:
        pass

    dedupe_key = _job_dedupe_key(school_id, day_key)
    payload = {
        "school_id": school_id,
        "rev": rev,
        "day_key": day_key,
        "reason": str(reason or "request_miss"),
        "queued_at": time.time(),
        "job_id": uuid.uuid4().hex,
    }

    try:
        if not bool(cache.add(dedupe_key, json.dumps(payload, ensure_ascii=False), timeout=_job_dedupe_ttl_seconds())):
            _metrics_incr("metrics:snapshot_queue:deduped")
            return {"queued": False, "duplicate": True, "dedupe_key": dedupe_key}
    except Exception:
        pass

    try:
        conn.rpush(_queue_name(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        _metrics_incr("metrics:snapshot_queue:enqueued")
        return {"queued": True, "dedupe_key": dedupe_key, "job": payload}
    except Exception as exc:
        try:
            cache.delete(dedupe_key)
        except Exception:
            pass
        _metrics_incr("metrics:snapshot_queue:enqueue_error")
        logger.exception("snapshot_queue enqueue failed school_id=%s rev=%s day_key=%s", school_id, rev, day_key)
        return {"queued": False, "reason": exc.__class__.__name__}


def dequeue_snapshot_build(*, block_timeout: int = 5) -> dict[str, Any] | None:
    if not snapshot_queue_available():
        return None
    conn = _get_cache_redis_connection()
    if conn is None:
        return None

    try:
        item = conn.blpop(_queue_name(), timeout=max(0, int(block_timeout or 0)))
    except Exception:
        item = None
    if not item:
        return None

    try:
        _, raw = item
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw or "{}")
        if isinstance(payload, dict):
            _metrics_incr("metrics:snapshot_queue:dequeued")
            dequeued_at = time.time()
            payload["_dequeued_at"] = dequeued_at

            try:
                queued_at = float(payload.get("queued_at") or 0.0)
            except Exception:
                queued_at = 0.0
            if queued_at > 0:
                queue_wait_ms = int(max(0.0, (dequeued_at - queued_at) * 1000.0))
                payload["_queue_wait_ms"] = queue_wait_ms
                _metrics_add("metrics:snapshot_queue:queue_wait_sum_ms", queue_wait_ms)
                _metrics_set_max("metrics:snapshot_queue:queue_wait_max_ms", queue_wait_ms)
            return payload
    except Exception:
        _metrics_incr("metrics:snapshot_queue:decode_error")
        logger.exception("snapshot_queue decode failed")
    return None


def wait_for_materialized_snapshot(*, school_id: int, rev: int, day_key: str, timeout_s: float | None = None):
    try:
        from schedule import api_views as av
    except Exception:
        return None

    limit = queue_wait_timeout_seconds() if timeout_s is None else max(0.0, float(timeout_s))
    t0 = time.time()
    key = av._steady_cache_key_for_school_rev(int(school_id), int(rev), day_key=day_key)
    while (time.time() - t0) < limit:
        try:
            entry = av._snapshot_cache_entry_from_cached(cache.get(key))
        except Exception:
            entry = None
        if isinstance(entry, dict) and isinstance(entry.get("snap"), dict):
            return entry
        time.sleep(0.05)
    return None


def _store_materialized_snapshot(*, school_id: int, rev: int, day_key: str, snap: dict) -> dict[str, Any]:
    from schedule import api_views as av

    ttl = int(av.compute_dynamic_ttl_seconds(snap))
    ttl = int(av._stable_ttl_with_jitter(ttl, seed=f"{int(school_id)}:{int(rev)}:{day_key}"))
    try:
        stale_ttl = int(av._active_fallback_steady_ttl_seconds(snap)) if av._is_active_window(snap) else max(600, ttl)
    except Exception:
        stale_ttl = max(600, ttl)

    entry = av._snapshot_cache_entry(snap)
    steady_key = av._steady_cache_key_for_school_rev(int(school_id), int(rev), day_key=day_key)
    cache.set(steady_key, entry, timeout=ttl)
    cache.set(av._stale_snapshot_fallback_key(int(school_id), day_key=day_key), entry, timeout=stale_ttl)

    try:
        from display.cache_utils import keys as display_keys

        school_blob = json.dumps(snap, ensure_ascii=False)
        school_ttl = int(getattr(settings, "SCHOOL_SNAPSHOT_TTL", 1200) or 1200)
        cache.set(display_keys.snapshot(int(school_id), int(rev), str(day_key)), school_blob, timeout=school_ttl)
        cache.set(display_keys.school_snapshot_stale(int(school_id), str(day_key)), school_blob, timeout=60 * 60 * 6)
    except Exception:
        logger.exception("snapshot_materialized cache_write_failed school_id=%s rev=%s", school_id, rev)

    return {"entry": entry, "ttl": ttl, "stale_ttl": stale_ttl, "steady_key": steady_key}


def materialize_snapshot_for_school(
    *,
    school_id: int,
    rev: int | None = None,
    day_key: str | None = None,
    queued_at: float | None = None,
    dequeued_at: float | None = None,
    source: str = "worker",
) -> dict[str, Any]:
    from schedule import api_views as av

    school_id = int(school_id or 0)
    if not school_id:
        return {"ok": False, "reason": "school_id_invalid"}

    settings_obj = av._get_settings_by_school_id(school_id)
    if not settings_obj:
        _metrics_incr("metrics:snapshot_queue:settings_missing")
        return {"ok": False, "reason": "settings_missing", "school_id": school_id}

    try:
        settings_obj.refresh_from_db()
    except Exception:
        pass

    current_rev = int(getattr(settings_obj, "schedule_revision", 0) or 0)
    target_rev = current_rev
    target_day_key = av._snapshot_cache_day_key(day_key)

    queue_wait_ms = None
    try:
        queued_at_f = float(queued_at or 0.0)
    except Exception:
        queued_at_f = 0.0
    try:
        dequeued_at_f = float(dequeued_at or 0.0)
    except Exception:
        dequeued_at_f = 0.0
    if queued_at_f > 0:
        ref_dequeued = dequeued_at_f if dequeued_at_f > 0 else time.time()
        queue_wait_ms = int(max(0.0, (ref_dequeued - queued_at_f) * 1000.0))
        # Queue wait is normally measured at dequeue time. Record it here only
        # for direct materialize calls that bypass dequeue_snapshot_build().
        if dequeued_at_f <= 0:
            _metrics_add("metrics:snapshot_queue:queue_wait_sum_ms", queue_wait_ms)
            _metrics_set_max("metrics:snapshot_queue:queue_wait_max_ms", queue_wait_ms)

    lock_acquired = False
    try:
        lock_acquired = bool(av._acquire_build_lock(school_id, target_rev, day_key=target_day_key))
    except Exception:
        lock_acquired = True

    if not lock_acquired:
        _metrics_incr("metrics:snapshot_queue:lock_busy")
        return {
            "ok": False,
            "reason": "lock_busy",
            "school_id": school_id,
            "rev": target_rev,
            "day_key": target_day_key,
        }

    try:
        entry_existing = av._snapshot_cache_entry_from_cached(
            cache.get(av._steady_cache_key_for_school_rev(school_id, target_rev, day_key=target_day_key))
        )
        if isinstance(entry_existing, dict) and isinstance(entry_existing.get("snap"), dict):
            _metrics_incr("metrics:snapshot_queue:already_materialized")
            return {
                "ok": True,
                "reason": "already_materialized",
                "school_id": school_id,
                "rev": target_rev,
                "day_key": target_day_key,
            }

        build_started = time.monotonic()
        snap, build_ms = av._build_snapshot_payload(None, settings_obj, school_id=school_id, rev=target_rev)
        if not isinstance(snap, dict):
            snap = av._fallback_payload("تعذر تجهيز بيانات الشاشة")
            build_ms = int((time.monotonic() - build_started) * 1000)

        try:
            meta = snap.get("meta")
            if not isinstance(meta, dict):
                meta = {}
                snap["meta"] = meta
            meta["cache"] = "MISS"
            meta["materialized"] = True
            meta["materialized_source"] = str(source or "worker")
            meta["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        except Exception:
            pass

        store_info = _store_materialized_snapshot(
            school_id=school_id,
            rev=target_rev,
            day_key=target_day_key,
            snap=snap,
        )
        process_ms = int((time.monotonic() - build_started) * 1000)
        _metrics_add("metrics:snapshot_queue:process_sum_ms", process_ms)
        _metrics_set_max("metrics:snapshot_queue:process_max_ms", process_ms)

        _metrics_incr("metrics:snapshot_queue:materialized")
        logger.info(
            "snapshot_materialized school_id=%s requested_rev=%s built_rev=%s day_key=%s queue_wait_ms=%s build_ms=%s process_ms=%s source=%s ttl=%s stale_ttl=%s",
            school_id,
            int(rev or 0),
            target_rev,
            target_day_key,
            int(queue_wait_ms or 0),
            int(build_ms),
            int(process_ms),
            str(source or "worker"),
            int(store_info.get("ttl", 0) or 0),
            int(store_info.get("stale_ttl", 0) or 0),
        )
        return {
            "ok": True,
            "school_id": school_id,
            "requested_rev": int(rev or 0),
            "built_rev": target_rev,
            "day_key": target_day_key,
            "queue_wait_ms": int(queue_wait_ms or 0),
            "build_ms": int(build_ms),
            "process_ms": int(process_ms),
            "ttl": int(store_info.get("ttl", 0) or 0),
            "stale_ttl": int(store_info.get("stale_ttl", 0) or 0),
        }
    except Exception as exc:
        _metrics_incr("metrics:snapshot_queue:error")
        logger.exception("snapshot_materialize failed school_id=%s rev=%s day_key=%s", school_id, rev, day_key)
        return {"ok": False, "reason": exc.__class__.__name__, "school_id": school_id}
    finally:
        try:
            cache.delete(f"lock:snapshot:{int(school_id)}:day:{str(target_day_key)}")
        except Exception:
            pass


def complete_snapshot_job(job: dict[str, Any] | None) -> None:
    if not isinstance(job, dict):
        return

    try:
        queued_at = float(job.get("queued_at") or 0.0)
    except Exception:
        queued_at = 0.0
    if queued_at > 0:
        e2e_ms = int(max(0.0, (time.time() - queued_at) * 1000.0))
        _metrics_add("metrics:snapshot_queue:e2e_sum_ms", e2e_ms)
        _metrics_set_max("metrics:snapshot_queue:e2e_max_ms", e2e_ms)

    try:
        cache.delete(_job_dedupe_key(int(job.get("school_id") or 0), str(job.get("day_key") or "")))
    except Exception:
        pass
