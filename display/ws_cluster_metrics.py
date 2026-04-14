from __future__ import annotations

import hashlib
import logging
import os
import socket
import time
import uuid
from typing import Any

from django.conf import settings


logger = logging.getLogger(__name__)


def _redis():
    try:
        from django_redis import get_redis_connection  # type: ignore

        return get_redis_connection("default")
    except Exception:
        return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _active_ttl_seconds() -> int:
    try:
        return max(30, min(900, int(getattr(settings, "WS_CLUSTER_ACTIVE_TTL", 120) or 120)))
    except Exception:
        return 120


def _retention_seconds() -> int:
    try:
        return max(_active_ttl_seconds() * 2, min(86400, int(getattr(settings, "WS_CLUSTER_EVENT_RETENTION", 3600) or 3600)))
    except Exception:
        return 3600


def _key(name: str) -> str:
    return f"metrics:ws:cluster:{name}"


def _event_member(kind: str, channel_name: str) -> str:
    return f"{int(_now_ms())}:{kind}:{socket.gethostname()}:{os.getpid()}:{channel_name}:{uuid.uuid4().hex[:8]}"


def _device_fingerprint(token: str | None, device_id: str | None) -> str:
    raw = f"{str(token or '').strip()}|{str(device_id or '').strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def enabled() -> bool:
    return _redis() is not None


def register_connect(*, channel_name: str, token: str | None, device_id: str | None) -> dict[str, Any]:
    conn = _redis()
    if conn is None:
        return {"cluster_enabled": False}

    now_ms = _now_ms()
    try:
        conn.zadd(_key("active"), {channel_name: now_ms})
        conn.expire(_key("active"), _retention_seconds())
    except Exception:
        logger.exception("ws_cluster active register failed")

    recent_key = _key(f"recent:{_device_fingerprint(token, device_id)}")
    was_recent = False
    try:
        was_recent = bool(conn.exists(recent_key))
        conn.setex(recent_key, _retention_seconds(), str(now_ms))
    except Exception:
        logger.exception("ws_cluster recent connect failed")

    event_kind = "reconnect" if was_recent else "connect"
    try:
        conn.zadd(_key(event_kind), {_event_member(event_kind, channel_name): now_ms})
        conn.expire(_key(event_kind), _retention_seconds())
    except Exception:
        logger.exception("ws_cluster %s event failed", event_kind)

    return {"cluster_enabled": True, "event": event_kind}


def heartbeat(*, channel_name: str) -> None:
    conn = _redis()
    if conn is None:
        return
    try:
        conn.zadd(_key("active"), {channel_name: _now_ms()})
        conn.expire(_key("active"), _retention_seconds())
    except Exception:
        logger.exception("ws_cluster heartbeat failed")


def register_disconnect(*, channel_name: str, close_code: int | None = None) -> None:
    conn = _redis()
    if conn is None:
        return

    now_ms = _now_ms()
    try:
        conn.zrem(_key("active"), channel_name)
    except Exception:
        logger.exception("ws_cluster active remove failed")

    try:
        conn.zadd(_key("disconnect"), {_event_member("disconnect", channel_name): now_ms})
        conn.expire(_key("disconnect"), _retention_seconds())
    except Exception:
        logger.exception("ws_cluster disconnect event failed")

    if close_code is not None:
        try:
            conn.hincrby(_key("disconnect_codes"), str(int(close_code)), 1)
            conn.expire(_key("disconnect_codes"), _retention_seconds())
        except Exception:
            logger.exception("ws_cluster disconnect code failed")


def snapshot() -> dict[str, Any]:
    conn = _redis()
    if conn is None:
        return {
            "enabled": False,
            "active_ws": 0,
            "rates_60s": {"connect": 0, "reconnect": 0, "disconnect": 0},
            "rates_300s": {"connect": 0, "reconnect": 0, "disconnect": 0},
            "disconnect_codes": {},
        }

    now_ms = _now_ms()
    retention_ms = _retention_seconds() * 1000
    active_threshold_ms = now_ms - (_active_ttl_seconds() * 1000)
    try:
        conn.zremrangebyscore(_key("active"), 0, active_threshold_ms - 1)
        for name in ("connect", "reconnect", "disconnect"):
            conn.zremrangebyscore(_key(name), 0, now_ms - retention_ms)
    except Exception:
        logger.exception("ws_cluster prune failed")

    def _count(name: str, window_sec: int) -> int:
        try:
            return int(conn.zcount(_key(name), now_ms - (window_sec * 1000), now_ms) or 0)
        except Exception:
            return 0

    try:
        active_ws = int(conn.zcount(_key("active"), active_threshold_ms, now_ms) or 0)
    except Exception:
        active_ws = 0

    try:
        raw_codes = conn.hgetall(_key("disconnect_codes")) or {}
        disconnect_codes = {
            (k.decode("utf-8") if isinstance(k, bytes) else str(k)): int(v.decode("utf-8") if isinstance(v, bytes) else v)
            for k, v in raw_codes.items()
        }
    except Exception:
        disconnect_codes = {}

    return {
        "enabled": True,
        "active_ws": active_ws,
        "totals_retained": {
            "connect": _count("connect", max(60, _retention_seconds())),
            "reconnect": _count("reconnect", max(60, _retention_seconds())),
            "disconnect": _count("disconnect", max(60, _retention_seconds())),
        },
        "rates_60s": {
            "connect": _count("connect", 60),
            "reconnect": _count("reconnect", 60),
            "disconnect": _count("disconnect", 60),
        },
        "rates_300s": {
            "connect": _count("connect", 300),
            "reconnect": _count("reconnect", 300),
            "disconnect": _count("disconnect", 300),
        },
        "disconnect_codes": disconnect_codes,
    }
