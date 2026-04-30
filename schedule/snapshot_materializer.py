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
from schedule.snapshot_observability import (
    metric_add as _obs_metric_add,
    metric_incr as _obs_metric_incr,
    metric_set_max as _obs_metric_set_max,
    observe_snapshot_build as _obs_snapshot_build,
    observe_snapshot_queue as _obs_snapshot_queue,
)


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
    _obs_metric_incr(key)


def _metrics_add(key: str, delta: int) -> None:
    _obs_metric_add(key, int(delta))


def _metrics_set_max(key: str, value: int) -> None:
    _obs_metric_set_max(key, int(value))


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
            "DISPLAY_SNAPSHOT_PENDING_TTL_SEC",
            _env_int(
                "DISPLAY_SNAPSHOT_PENDING_TTL_SEC",
                _env_int("DISPLAY_SNAPSHOT_JOB_DEDUPE_TTL", 30, min_v=5, max_v=300),
                min_v=5,
                max_v=600,
            ),
        )
        or 30
    )


def _enqueue_debounce_seconds() -> int:
    value = getattr(
        settings,
        "DISPLAY_SNAPSHOT_DEBOUNCE_SEC",
        _env_int(
            "DISPLAY_SNAPSHOT_DEBOUNCE_SEC",
            _env_int("DISPLAY_SNAPSHOT_REBUILD_DEBOUNCE_SEC", 3, min_v=0, max_v=60),
            min_v=0,
            max_v=60,
        ),
    )
    try:
        return max(0, min(60, int(value)))
    except Exception:
        return 3


def _latest_rev_ttl_seconds() -> int:
    return int(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_LATEST_REV_TTL_SEC",
            _env_int("DISPLAY_SNAPSHOT_LATEST_REV_TTL_SEC", 120, min_v=30, max_v=3600),
        )
        or 120
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
    return _pending_job_key(school_id, day_key)


def _enqueue_debounce_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:debounce:{int(school_id)}:{normalize_day_key(day_key)}"


def _pending_job_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:queue:pending:{int(school_id)}:{normalize_day_key(day_key)}"


def _latest_rev_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:latest_rev:{int(school_id)}:{normalize_day_key(day_key)}"


def _materialized_rev_key(school_id: int, day_key: str) -> str:
    return f"display:snapshot:materialized_rev:{int(school_id)}:{normalize_day_key(day_key)}"


def _get_cache_redis_connection():
    try:
        from django_redis import get_redis_connection  # type: ignore

        return get_redis_connection("default")
    except Exception:
        return None


def _get_queue_redis_connection():
    url = str(getattr(settings, "REDIS_CHANNELS_URL", "") or "").strip()
    if url:
        try:
            import redis  # type: ignore

            return redis.Redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
                health_check_interval=30,
            )
        except Exception:
            logger.exception("snapshot_queue channels redis connection failed")

    return _get_cache_redis_connection()


def _redis_get_int(conn, key: str) -> int | None:
    try:
        raw = conn.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return int(raw)
    except Exception:
        return None


def _redis_set_latest_revision(conn, key: str, rev: int, ttl: int) -> tuple[int, bool]:
    rev = int(rev or 0)
    ttl = int(ttl or 120)
    script = """
local cur = redis.call('GET', KEYS[1])
local cur_i = tonumber(cur or '0') or 0
local next_i = tonumber(ARGV[1]) or 0
if next_i >= cur_i then
  redis.call('SET', KEYS[1], tostring(next_i), 'EX', tonumber(ARGV[2]))
  return {cur_i, next_i}
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return {cur_i, cur_i}
"""
    try:
        result = conn.eval(script, 1, key, int(rev), int(ttl))
        previous = int(result[0] or 0) if isinstance(result, (list, tuple)) else 0
        latest = int(result[1] or rev) if isinstance(result, (list, tuple)) else rev
        return latest, bool(previous and latest > previous)
    except Exception:
        previous = _redis_get_int(conn, key) or 0
        latest = max(int(previous), int(rev))
        try:
            conn.set(key, str(latest), ex=ttl)
        except Exception:
            pass
        return latest, bool(previous and latest > previous)


def _redis_delete_if_value(conn, key: str, expected: str) -> bool:
    script = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""
    try:
        return bool(conn.eval(script, 1, key, str(expected)))
    except Exception:
        try:
            raw = conn.get(key)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if str(raw or "") == str(expected):
                return bool(conn.delete(key))
        except Exception:
            pass
    return False


def _worker_job_lock_ttl_seconds() -> int:
    return int(
        getattr(
            settings,
            "DISPLAY_SNAPSHOT_WORKER_JOB_LOCK_TTL_SEC",
            _env_int("DISPLAY_SNAPSHOT_WORKER_JOB_LOCK_TTL_SEC", 45, min_v=5, max_v=300),
        )
        or 45
    )


def snapshot_job_lock_key(*, school_id: int, day_key: str, rev: int) -> str:
    return f"snapshot_worker_lock:{int(school_id)}:{normalize_day_key(day_key)}:{int(rev or 0)}"


def acquire_snapshot_job_lock(*, school_id: int, day_key: str, rev: int, token: str | None = None) -> tuple[bool, str, str]:
    lock_token = str(token or uuid.uuid4().hex)
    lock_key = snapshot_job_lock_key(school_id=int(school_id), day_key=str(day_key), rev=int(rev or 0))
    conn = _get_queue_redis_connection()
    if conn is None:
        return True, lock_key, lock_token
    try:
        acquired = bool(conn.set(lock_key, lock_token, nx=True, ex=_worker_job_lock_ttl_seconds()))
    except Exception:
        acquired = True
    return acquired, lock_key, lock_token


def release_snapshot_job_lock(*, lock_key: str, token: str) -> bool:
    conn = _get_queue_redis_connection()
    if conn is None:
        return False
    return _redis_delete_if_value(conn, str(lock_key), str(token))


def get_latest_snapshot_revision(*, school_id: int, day_key: str) -> int | None:
    conn = _get_queue_redis_connection()
    if conn is None:
        return None
    return _redis_get_int(conn, _latest_rev_key(int(school_id), str(day_key)))


def get_materialized_snapshot_revision(*, school_id: int, day_key: str) -> int | None:
    conn = _get_queue_redis_connection()
    if conn is None:
        return None
    return _redis_get_int(conn, _materialized_rev_key(int(school_id), str(day_key)))


def get_pending_snapshot_job_id(*, school_id: int, day_key: str) -> str | None:
    conn = _get_queue_redis_connection()
    if conn is None:
        return None
    try:
        raw = conn.get(_pending_job_key(int(school_id), str(day_key)))
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = str(raw or "").strip()
        return value or None
    except Exception:
        return None


def get_cached_snapshot_revision(*, school_id: int, day_key: str) -> int | None:
    try:
        from schedule import api_views as av
    except Exception:
        return None

    steady_key = av._steady_cache_key_for_school_rev(int(school_id), 0, day_key=day_key)
    try:
        entry, _ = av._validated_snapshot_cache_entry_from_value(
            cache.get(steady_key),
            cache_key=steady_key,
        )
    except Exception:
        return None
    if not isinstance(entry, dict):
        return None
    try:
        snap = entry.get("snap") or {}
        meta = snap.get("meta") if isinstance(snap, dict) else {}
        rev = int((meta or {}).get("schedule_revision") or 0)
    except Exception:
        rev = 0
    return rev or None


def _job_not_before(payload: dict[str, Any]) -> float:
    try:
        return float(payload.get("not_before") or 0.0)
    except Exception:
        return 0.0


def snapshot_queue_available() -> bool:
    if str(getattr(settings, "REDIS_CHANNELS_URL", "") or "").strip():
        return True
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
    conn = _get_queue_redis_connection()
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
        return {"queued": False, "reason": "invalid_payload", "debounced": False, "coalesced": False, "deduped": False}
    if not snapshot_async_build_enabled():
        return {"queued": False, "reason": "async_disabled", "debounced": False, "coalesced": False, "deduped": False}
    if not snapshot_queue_available():
        return {"queued": False, "reason": "queue_unavailable", "debounced": False, "coalesced": False, "deduped": False}

    if _require_worker_alive_for_enqueue():
        try:
            worker_alive = bool(snapshot_worker_status().get("alive"))
        except Exception:
            worker_alive = False
        if not worker_alive:
            _metrics_incr("metrics:snapshot_queue:worker_unavailable")
            _obs_snapshot_queue(
                logger=logger,
                decision="skipped",
                school_id=school_id,
                rev=rev,
                latest_rev=rev,
                day_key=day_key,
                reason="worker_unavailable",
            )
            return {"queued": False, "reason": "worker_unavailable", "debounced": False, "coalesced": False, "deduped": False}

    conn = _get_queue_redis_connection()
    if conn is None:
        return {"queued": False, "reason": "redis_unavailable", "debounced": False, "coalesced": False, "deduped": False}

    latest_key = _latest_rev_key(school_id, day_key)
    pending_key = _pending_job_key(school_id, day_key)
    debounce_key = _enqueue_debounce_key(school_id, day_key)
    latest_rev = rev
    latest_replaced = False
    try:
        latest_rev, latest_replaced = _redis_set_latest_revision(
            conn,
            latest_key,
            rev,
            _latest_rev_ttl_seconds(),
        )
        if latest_replaced:
            _metrics_incr("metrics:snapshot_queue:latest_revision_replaced")
    except Exception:
        latest_rev = rev

    coalesced = bool(latest_replaced or int(latest_rev or 0) > int(rev or 0))
    try:
        from schedule import api_views as av

        steady_key = av._steady_cache_key_for_school_rev(school_id, int(latest_rev or rev), day_key=day_key)
        entry_existing, _ = av._validated_snapshot_cache_entry_from_value(
            cache.get(steady_key),
            min_rev=int(latest_rev or rev),
            cache_key=steady_key,
        )
        if isinstance(entry_existing, dict) and isinstance(entry_existing.get("snap"), dict):
            _metrics_incr("metrics:snapshot_queue:already_materialized")
            _obs_snapshot_queue(
                logger=logger,
                decision="skipped",
                school_id=school_id,
                rev=int(latest_rev or rev),
                latest_rev=int(latest_rev or 0),
                day_key=day_key,
                reason="already_cached",
            )
            return {
                "queued": False,
                "reason": "already_cached",
                "deduped": False,
                "debounced": False,
                "coalesced": coalesced,
                "latest_rev": int(latest_rev or 0),
            }
    except Exception:
        pass
    debounce_sec = max(0, int(_enqueue_debounce_seconds()))
    dedupe_key = pending_key
    now = time.time()
    job_id = uuid.uuid4().hex

    debounced = False
    try:
        if debounce_sec > 0 and not bool(conn.set(debounce_key, str(latest_rev), nx=True, ex=debounce_sec)):
            debounced = True
            _metrics_incr("metrics:snapshot_queue:debounced")
            if coalesced:
                _metrics_incr("metrics:snapshot_queue:coalesced")
            _obs_snapshot_queue(
                logger=logger,
                decision="skipped",
                school_id=school_id,
                rev=rev,
                latest_rev=int(latest_rev or 0),
                day_key=day_key,
                reason="debounced",
            )
            return {
                "queued": False,
                "reason": "debounced",
                "debounced": True,
                "coalesced": coalesced,
                "deduped": False,
                "latest_rev": int(latest_rev or 0),
                "dedupe_key": dedupe_key,
                "debounce_key": debounce_key,
            }
    except Exception:
        pass

    payload = {
        "school_id": school_id,
        "rev": int(latest_rev or rev),
        "day_key": day_key,
        "reason": str(reason or "request_miss"),
        "queued_at": now,
        "not_before": now + max(0, int(_enqueue_debounce_seconds())),
        "job_id": job_id,
        "latest_rev_key": latest_key,
        "pending_key": pending_key,
    }

    try:
        if not bool(conn.set(dedupe_key, job_id, nx=True, ex=_job_dedupe_ttl_seconds())):
            _metrics_incr("metrics:snapshot_queue:deduped")
            if coalesced:
                _metrics_incr("metrics:snapshot_queue:coalesced")
            _obs_snapshot_queue(
                logger=logger,
                decision="deduped",
                school_id=school_id,
                rev=rev,
                latest_rev=int(latest_rev or 0),
                day_key=day_key,
                reason="deduped",
                job_id=job_id,
            )
            return {
                "queued": False,
                "reason": "deduped",
                "duplicate": True,
                "deduped": True,
                "debounced": debounced,
                "coalesced": coalesced,
                "latest_rev": int(latest_rev or 0),
                "dedupe_key": dedupe_key,
                "debounce_key": debounce_key,
            }
    except Exception:
        pass

    try:
        conn.rpush(_queue_name(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        _metrics_incr("metrics:snapshot_queue:enqueued")
        _obs_snapshot_queue(
            logger=logger,
            decision="queued",
            school_id=school_id,
            rev=rev,
            latest_rev=int(latest_rev or 0),
            day_key=day_key,
            reason=str(reason or "request_miss"),
            job_id=job_id,
        )
        return {
            "queued": True,
            "reason": "queued",
            "deduped": False,
            "debounced": False,
            "coalesced": coalesced,
            "dedupe_key": dedupe_key,
            "debounce_key": debounce_key,
            "latest_rev": int(latest_rev or 0),
            "job": payload,
        }
    except Exception as exc:
        try:
            _redis_delete_if_value(conn, dedupe_key, job_id)
        except Exception:
            pass
        _metrics_incr("metrics:snapshot_queue:enqueue_error")
        logger.exception("snapshot_queue enqueue failed school_id=%s rev=%s day_key=%s", school_id, rev, day_key)
        _obs_snapshot_queue(
            logger=logger,
            decision="skipped",
            school_id=school_id,
            rev=rev,
            latest_rev=int(latest_rev or 0),
            day_key=day_key,
            reason=exc.__class__.__name__,
            job_id=job_id,
        )
        return {
            "queued": False,
            "reason": exc.__class__.__name__,
            "deduped": False,
            "debounced": False,
            "coalesced": coalesced,
            "latest_rev": int(latest_rev or 0),
        }


def dequeue_snapshot_build(*, block_timeout: int = 5) -> dict[str, Any] | None:
    if not snapshot_queue_available():
        return None
    conn = _get_queue_redis_connection()
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
            school_id = int(payload.get("school_id") or 0)
            day_key = normalize_day_key(str(payload.get("day_key") or ""))
            job_id = str(payload.get("job_id") or "")
            pending_key = str(payload.get("pending_key") or _pending_job_key(school_id, day_key))

            try:
                pending_job_id = conn.get(pending_key)
                if isinstance(pending_job_id, bytes):
                    pending_job_id = pending_job_id.decode("utf-8")
                if pending_job_id and job_id and str(pending_job_id) != job_id:
                    _metrics_incr("metrics:snapshot_queue:outdated_job_dropped")
                    _obs_snapshot_queue(
                        logger=logger,
                        decision="skipped",
                        school_id=school_id,
                        rev=int(payload.get("rev") or 0),
                        latest_rev=int(payload.get("rev") or 0),
                        day_key=day_key,
                        reason="outdated_job_dropped",
                        job_id=job_id,
                        pending_job_id=str(pending_job_id),
                    )
                    return None
            except Exception:
                pass

            not_before = _job_not_before(payload)
            now = time.time()
            if not_before > now:
                try:
                    payload["_debounce_requeues"] = int(payload.get("_debounce_requeues") or 0) + 1
                    conn.rpush(_queue_name(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                except Exception:
                    pass
                return None

            latest_rev = _redis_get_int(conn, _latest_rev_key(school_id, day_key))
            try:
                job_rev = int(payload.get("rev") or 0)
            except Exception:
                job_rev = 0
            if latest_rev is not None and latest_rev > job_rev:
                payload["_coalesced_from_rev"] = job_rev
                payload["rev"] = int(latest_rev)
                _metrics_incr("metrics:snapshot_queue:coalesced")
                _obs_snapshot_queue(
                    logger=logger,
                    decision="deduped",
                    school_id=school_id,
                    rev=job_rev,
                    latest_rev=int(latest_rev),
                    day_key=day_key,
                    reason="coalesced_to_latest",
                    job_id=job_id,
                )

            built_rev = _redis_get_int(conn, _materialized_rev_key(school_id, day_key))
            try:
                target_rev = int(payload.get("rev") or 0)
            except Exception:
                target_rev = 0
            if built_rev is not None and target_rev > 0 and built_rev >= target_rev:
                _metrics_incr("metrics:snapshot_queue:queue_skipped_outdated")
                _metrics_incr("metrics:snapshot_queue:outdated_job_dropped")
                payload["_skip_complete"] = True
                payload["_skip_reason"] = "already_materialized_latest"
                return payload

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
                _obs_snapshot_queue(
                    logger=logger,
                    decision="dequeued",
                    school_id=school_id,
                    rev=int(payload.get("rev") or 0),
                    latest_rev=int(latest_rev or payload.get("rev") or 0),
                    day_key=day_key,
                    reason="dequeued",
                    job_id=job_id,
                    queue_wait_ms=queue_wait_ms,
                )
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
            entry, _ = av._validated_snapshot_cache_entry_from_value(
                cache.get(key),
                min_rev=int(rev),
                cache_key=key,
            )
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
        conn = _get_queue_redis_connection()
        if conn is not None:
            conn.set(_materialized_rev_key(int(school_id), str(day_key)), int(rev), ex=_latest_rev_ttl_seconds())
    except Exception:
        pass

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
    target_day_key = av._snapshot_cache_day_key(day_key)
    requested_rev = int(rev or 0)
    latest_rev = None
    try:
        conn = _get_queue_redis_connection()
        if conn is not None:
            latest_rev = _redis_get_int(conn, _latest_rev_key(school_id, target_day_key))
    except Exception:
        latest_rev = None
    target_rev = max(current_rev, requested_rev, int(latest_rev or 0))

    if latest_rev is not None and latest_rev > requested_rev:
        _metrics_incr("metrics:snapshot_queue:coalesced")

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
            _obs_snapshot_queue(
                logger=logger,
                decision="dequeued",
                school_id=school_id,
                rev=requested_rev,
                latest_rev=int(latest_rev or target_rev),
                day_key=target_day_key,
                reason="direct_materialize",
                queue_wait_ms=queue_wait_ms,
            )

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
        steady_key = av._steady_cache_key_for_school_rev(school_id, target_rev, day_key=target_day_key)
        entry_existing, existing_reason = av._validated_snapshot_cache_entry_from_value(
            cache.get(steady_key),
            min_rev=int(target_rev),
            cache_key=steady_key,
        )
        built_rev_existing = None
        try:
            conn = _get_queue_redis_connection()
            if conn is not None:
                built_rev_existing = _redis_get_int(conn, _materialized_rev_key(school_id, target_day_key))
        except Exception:
            built_rev_existing = None
        if built_rev_existing is None and isinstance(entry_existing, dict):
            try:
                snap_existing = entry_existing.get("snap") or {}
                meta_existing = snap_existing.get("meta") if isinstance(snap_existing, dict) else {}
                built_rev_existing = int((meta_existing or {}).get("schedule_revision") or 0)
            except Exception:
                built_rev_existing = None

        if built_rev_existing is not None and built_rev_existing >= target_rev:
            _metrics_incr("metrics:snapshot_queue:queue_skipped_outdated")
            return {
                "ok": True,
                "reason": "already_materialized_latest",
                "school_id": school_id,
                "requested_rev": requested_rev,
                "built_rev": int(built_rev_existing),
                "day_key": target_day_key,
                "queue_wait_ms": int(queue_wait_ms or 0),
            }

        if isinstance(entry_existing, dict) and isinstance(entry_existing.get("snap"), dict):
            _metrics_incr("metrics:snapshot_queue:already_materialized")
            return {
                "ok": True,
                "reason": "already_materialized",
                "school_id": school_id,
                "rev": target_rev,
                "requested_rev": requested_rev,
                "built_rev": target_rev,
                "day_key": target_day_key,
            }
        if existing_reason == "past_wake_boundary":
            _obs_snapshot_queue(
                logger=logger,
                decision="skipped",
                school_id=school_id,
                rev=requested_rev,
                latest_rev=target_rev,
                day_key=target_day_key,
                reason=existing_reason,
            )

        build_started = time.monotonic()
        _obs_snapshot_build(
            logger=logger,
            stage="start",
            source="queue" if str(source or "worker") == "worker" else str(source or "worker"),
            school_id=school_id,
            rev=target_rev,
            day_key=target_day_key,
        )
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
            meta["schedule_revision"] = int(target_rev)
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
        soft_timeout_ms = int(av._snapshot_build_soft_timeout_ms())
        if int(build_ms) >= soft_timeout_ms:
            _metrics_incr("metrics:snapshot_build:soft_timeout")
        _metrics_add("metrics:snapshot_queue:process_sum_ms", process_ms)
        _metrics_set_max("metrics:snapshot_queue:process_max_ms", process_ms)

        _metrics_incr("metrics:snapshot_queue:materialized")
        build_source = "queue" if str(source or "worker") == "worker" else str(source or "worker")
        _obs_snapshot_build(
            logger=logger,
            stage="end",
            source=build_source,
            school_id=school_id,
            rev=target_rev,
            day_key=target_day_key,
            duration_ms=int(build_ms),
            result="materialized",
            queue_wait_ms=int(queue_wait_ms or 0),
            process_ms=int(process_ms),
            ttl=int(store_info.get("ttl", 0) or 0),
            stale_ttl=int(store_info.get("stale_ttl", 0) or 0),
            soft_timeout_ms=soft_timeout_ms,
            soft_timeout_exceeded=bool(int(build_ms) >= soft_timeout_ms),
        )
        return {
            "ok": True,
            "school_id": school_id,
            "requested_rev": requested_rev,
            "built_rev": target_rev,
            "latest_rev": int(latest_rev or target_rev),
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
        conn = _get_queue_redis_connection()
        if conn is not None:
            _redis_delete_if_value(
                conn,
                _pending_job_key(int(job.get("school_id") or 0), str(job.get("day_key") or "")),
                str(job.get("job_id") or ""),
            )
    except Exception:
        pass
