from __future__ import annotations

from typing import Any

from django.conf import settings


def _clean(value: object) -> str:
    return str(value or "").strip()


def redact_redis_url(value: object) -> object:
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


def cache_redis_url() -> str:
    try:
        return _clean(getattr(settings, "CACHE_REDIS_URL", ""))
    except Exception:
        return ""


def channels_redis_url() -> str:
    try:
        return _clean(getattr(settings, "CHANNELS_REDIS_URL", ""))
    except Exception:
        return ""


def redis_topology_summary() -> dict[str, Any]:
    cache_url = cache_redis_url()
    channels_url = channels_redis_url()
    split = bool(cache_url and channels_url and cache_url != channels_url)
    shared = bool(cache_url and channels_url and cache_url == channels_url)
    warnings: list[str] = []

    if not cache_url:
        warnings.append("cache_redis_missing")
    if not channels_url:
        warnings.append("channels_redis_missing")
    if shared:
        warnings.append("cache_and_channels_share_same_redis")

    return {
        "cache_url": cache_url,
        "channels_url": channels_url,
        "cache_url_redacted": redact_redis_url(cache_url),
        "channels_url_redacted": redact_redis_url(channels_url),
        "split": split,
        "shared": shared,
        "warnings": warnings,
    }
