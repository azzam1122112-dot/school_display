from __future__ import annotations

import json
import logging
import os
import zlib
from typing import Any

from django.conf import settings as dj_settings
from django.core.cache import cache


METRIC_TTL_SEC = 60 * 60 * 24


def metric_incr(key: str, delta: int = 1, *, ttl: int = METRIC_TTL_SEC) -> None:
    try:
        cache.incr(str(key), int(delta))
    except Exception:
        try:
            cache.add(str(key), 0, timeout=int(ttl))
            cache.incr(str(key), int(delta))
        except Exception:
            try:
                cur = int(cache.get(str(key)) or 0)
                cache.set(str(key), cur + int(delta), timeout=int(ttl))
            except Exception:
                pass


def metric_add(key: str, delta: int, *, ttl: int = METRIC_TTL_SEC) -> None:
    metric_incr(str(key), int(delta), ttl=int(ttl))


def metric_set_max(key: str, value: int, *, ttl: int = METRIC_TTL_SEC) -> None:
    try:
        cur = cache.get(str(key))
        cur_i = int(cur) if cur is not None else 0
        v = int(value)
        if v > cur_i:
            cache.set(str(key), v, timeout=int(ttl))
    except Exception:
        pass


def metric_get_int(key: str) -> int:
    try:
        value = cache.get(str(key))
        return int(value) if value is not None else 0
    except Exception:
        return 0


def _fmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if any(ch.isspace() for ch in text) or "=" in text or '"' in text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _int_setting(name: str, default: int, *, min_v: int = 1, max_v: int = 10_000) -> int:
    try:
        raw = getattr(dj_settings, name, os.getenv(name, default))
    except Exception:
        raw = os.getenv(name, default)
    try:
        value = int(raw or default)
    except Exception:
        value = int(default)
    return max(min_v, min(max_v, value))


def _sample_every(name: str, default: int) -> int:
    return _int_setting(name, default, min_v=1, max_v=10_000)


def _slow_ms(name: str, default: int) -> int:
    return _int_setting(name, default, min_v=1, max_v=60_000)


def _should_sample_log(*parts: Any, sample_every: int) -> bool:
    if int(sample_every) <= 1:
        return True
    signature = "|".join("" if value is None else str(value) for value in parts)
    bucket = zlib.crc32(signature.encode("utf-8")) % int(sample_every)
    return bucket == 0


def log_event(logger: logging.Logger, event: str, /, **fields: Any) -> None:
    parts = [f"event={_fmt_value(event)}"]
    for key in sorted(fields):
        parts.append(f"{key}={_fmt_value(fields[key])}")
    logger.info(" ".join(parts))


def observe_snapshot_cache(
    *,
    logger: logging.Logger,
    outcome: str,
    layer: str | None = None,
    school_id: int | None = None,
    rev: int | None = None,
    day_key: str | None = None,
    cache_key: str | None = None,
    reason: str | None = None,
) -> None:
    normalized = str(outcome or "").strip().lower() or "unknown"
    if normalized in {"hit", "miss"}:
        metric_incr(f"metrics:snapshot_cache:{normalized}")
    reason_text = str(reason or "").strip().lower()
    if reason_text == "older_revision":
        metric_incr("metrics:snapshot_cache:revision_reject")
    elif reason_text == "past_wake_boundary":
        metric_incr("metrics:snapshot_cache:wake_boundary_reject")
    always_log = reason_text in {"older_revision", "past_wake_boundary", "build_lock_contention"}
    sample_every = _sample_every(
        "DISPLAY_SNAPSHOT_CACHE_HIT_LOG_SAMPLE_EVERY" if normalized == "hit" else "DISPLAY_SNAPSHOT_CACHE_MISS_LOG_SAMPLE_EVERY",
        25 if normalized == "hit" else 8,
    )
    if always_log or _should_sample_log(
        "snapshot_cache",
        normalized,
        layer,
        school_id,
        rev,
        day_key,
        reason_text,
        sample_every=sample_every,
    ):
        log_event(
            logger,
            "snapshot_cache",
            outcome=normalized,
            layer=(layer or "none"),
            school_id=school_id,
            rev=rev,
            day_key=day_key,
            reason=(reason_text or "none"),
            cache_key=(cache_key or ""),
        )


def observe_snapshot_build(
    *,
    logger: logging.Logger,
    stage: str,
    source: str,
    school_id: int | None = None,
    rev: int | None = None,
    day_key: str | None = None,
    duration_ms: int | None = None,
    reason: str | None = None,
    payload_bytes: int | None = None,
    **extra_fields: Any,
) -> None:
    source_text = str(source or "unknown").strip().lower() or "unknown"
    stage_text = str(stage or "").strip().lower() or "unknown"
    if stage_text == "end":
        metric_incr("metrics:snapshot_build:count")
        metric_incr(f"metrics:snapshot_build:source:{source_text}:count")
        if duration_ms is not None:
            metric_add("metrics:snapshot_build:duration_ms:sum", int(duration_ms))
            metric_set_max("metrics:snapshot_build:duration_ms:max", int(duration_ms))
            metric_add(f"metrics:snapshot_build:source:{source_text}:duration_ms:sum", int(duration_ms))
            metric_set_max(f"metrics:snapshot_build:source:{source_text}:duration_ms:max", int(duration_ms))
    reason_text = str(reason or "").strip().lower() or "none"
    slow_build_ms = _slow_ms("DISPLAY_SNAPSHOT_BUILD_SLOW_LOG_MS", 750)
    always_log = (
        source_text in {"queue", "stale"}
        or (duration_ms is not None and int(duration_ms) >= slow_build_ms)
        or reason_text not in {"none", ""}
    )
    if stage_text == "start":
        always_log = source_text in {"queue", "stale"}
    sample_every = _sample_every(
        "DISPLAY_SNAPSHOT_BUILD_START_LOG_SAMPLE_EVERY" if stage_text == "start" else "DISPLAY_SNAPSHOT_BUILD_END_LOG_SAMPLE_EVERY",
        20 if stage_text == "start" else 10,
    )
    if always_log or _should_sample_log(
        "snapshot_build",
        stage_text,
        source_text,
        school_id,
        rev,
        day_key,
        reason_text,
        sample_every=sample_every,
    ):
        log_event(
            logger,
            "snapshot_build",
            stage=stage_text,
            source=source_text,
            school_id=school_id,
            rev=rev,
            day_key=day_key,
            duration_ms=duration_ms,
            payload_bytes=payload_bytes,
            reason=reason_text,
            **extra_fields,
        )


def observe_snapshot_queue(
    *,
    logger: logging.Logger,
    decision: str,
    school_id: int | None = None,
    rev: int | None = None,
    day_key: str | None = None,
    latest_rev: int | None = None,
    reason: str | None = None,
    job_id: str | None = None,
    queue_wait_ms: int | None = None,
    **extra_fields: Any,
) -> None:
    decision_text = str(decision or "").strip().lower() or "unknown"
    reason_text = str(reason or "").strip().lower() or "none"
    if decision_text == "queued":
        metric_incr("metrics:snapshot_queue:enqueue_count")
    elif decision_text in {"skipped", "deduped"}:
        metric_incr("metrics:snapshot_queue:skipped_enqueue")
    if decision_text == "deduped":
        metric_incr("metrics:snapshot_queue:deduplicated_jobs")
    if queue_wait_ms is not None:
        metric_add("metrics:snapshot_queue:queue_wait_time_ms:sum", int(queue_wait_ms))
        metric_set_max("metrics:snapshot_queue:queue_wait_time_ms:max", int(queue_wait_ms))
        metric_incr("metrics:snapshot_queue:queue_wait_time_ms:count")
    slow_wait_ms = _slow_ms("DISPLAY_SNAPSHOT_QUEUE_SLOW_WAIT_LOG_MS", 250)
    always_log = reason_text in {"worker_unavailable", "outdated_job_dropped"} or (
        queue_wait_ms is not None and int(queue_wait_ms) >= slow_wait_ms
    )
    sample_every = _sample_every("DISPLAY_SNAPSHOT_QUEUE_LOG_SAMPLE_EVERY", 12)
    if always_log or _should_sample_log(
        "snapshot_queue",
        decision_text,
        school_id,
        rev,
        latest_rev,
        day_key,
        reason_text,
        sample_every=sample_every,
    ):
        log_event(
            logger,
            "snapshot_queue",
            decision=decision_text,
            school_id=school_id,
            rev=rev,
            latest_rev=latest_rev,
            day_key=day_key,
            queue_wait_ms=queue_wait_ms,
            reason=reason_text,
            job_id=(job_id or ""),
            **extra_fields,
        )


def snapshot_metrics_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "snapshot_cache": {
            "hit": metric_get_int("metrics:snapshot_cache:hit"),
            "miss": metric_get_int("metrics:snapshot_cache:miss"),
            "revision_reject": metric_get_int("metrics:snapshot_cache:revision_reject"),
            "wake_boundary_reject": metric_get_int("metrics:snapshot_cache:wake_boundary_reject"),
        },
        "snapshot_build": {
            "count": metric_get_int("metrics:snapshot_build:count"),
            "soft_timeout": metric_get_int("metrics:snapshot_build:soft_timeout"),
            "duration_ms_sum": metric_get_int("metrics:snapshot_build:duration_ms:sum"),
            "duration_ms_max": metric_get_int("metrics:snapshot_build:duration_ms:max"),
            "source": {
                "inline": {
                    "count": metric_get_int("metrics:snapshot_build:source:inline:count"),
                    "duration_ms_sum": metric_get_int("metrics:snapshot_build:source:inline:duration_ms:sum"),
                    "duration_ms_max": metric_get_int("metrics:snapshot_build:source:inline:duration_ms:max"),
                },
                "queue": {
                    "count": metric_get_int("metrics:snapshot_build:source:queue:count"),
                    "duration_ms_sum": metric_get_int("metrics:snapshot_build:source:queue:duration_ms:sum"),
                    "duration_ms_max": metric_get_int("metrics:snapshot_build:source:queue:duration_ms:max"),
                },
                "stale": {
                    "count": metric_get_int("metrics:snapshot_build:source:stale:count"),
                    "duration_ms_sum": metric_get_int("metrics:snapshot_build:source:stale:duration_ms:sum"),
                    "duration_ms_max": metric_get_int("metrics:snapshot_build:source:stale:duration_ms:max"),
                },
            },
        },
        "queue": {
            "enqueue_count": metric_get_int("metrics:snapshot_queue:enqueue_count"),
            "skipped_enqueue": metric_get_int("metrics:snapshot_queue:skipped_enqueue"),
            "deduplicated_jobs": metric_get_int("metrics:snapshot_queue:deduplicated_jobs"),
            "queue_wait_time_ms_sum": metric_get_int("metrics:snapshot_queue:queue_wait_time_ms:sum"),
            "queue_wait_time_ms_max": metric_get_int("metrics:snapshot_queue:queue_wait_time_ms:max"),
            "queue_wait_time_ms_count": metric_get_int("metrics:snapshot_queue:queue_wait_time_ms:count"),
        },
    }

    try:
        total_builds = int(payload["snapshot_build"]["count"] or 0)
        build_sum = int(payload["snapshot_build"]["duration_ms_sum"] or 0)
        payload["snapshot_build"]["duration_ms_avg"] = int(build_sum / total_builds) if total_builds > 0 else 0
    except Exception:
        payload["snapshot_build"]["duration_ms_avg"] = 0

    try:
        wait_count = int(payload["queue"]["queue_wait_time_ms_count"] or 0)
        wait_sum = int(payload["queue"]["queue_wait_time_ms_sum"] or 0)
        payload["queue"]["queue_wait_time_ms_avg"] = int(wait_sum / wait_count) if wait_count > 0 else 0
    except Exception:
        payload["queue"]["queue_wait_time_ms_avg"] = 0

    return payload
