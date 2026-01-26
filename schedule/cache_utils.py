from __future__ import annotations

import hashlib
from datetime import timedelta

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from core.models import DisplayScreen
from schedule.models import SchoolSettings


def _school_rev_cache_key(school_id: int) -> str:
    return f"display:school_rev:{int(school_id)}"


def _school_rev_cache_ttl_seconds() -> int:
    # Long TTL; correctness is preserved because signals + refresh button update this value.
    # Even if cache is lost, DB fallback restores it.
    return 60 * 60 * 24 * 7  # 7 days


def get_cached_schedule_revision_for_school_id(school_id: int) -> int | None:
    if not school_id:
        return None
    try:
        v = cache.get(_school_rev_cache_key(int(school_id)))
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def set_cached_schedule_revision_for_school_id(school_id: int, rev: int) -> None:
    if not school_id:
        return
    try:
        cache.set(_school_rev_cache_key(int(school_id)), int(rev), timeout=_school_rev_cache_ttl_seconds())
    except Exception:
        pass


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def bump_schedule_revision_for_school_id(school_id: int) -> int | None:
    """Atomically increments schedule_revision for a school.

    Returns the new revision when possible.
    """
    if not school_id:
        return None

    # Use UPDATE to avoid triggering model signals recursively.
    try:
        SchoolSettings.objects.filter(school_id=int(school_id)).update(schedule_revision=F("schedule_revision") + 1)
    except Exception:
        return None

    try:
        new_rev = int(
            SchoolSettings.objects.filter(school_id=int(school_id)).values_list("schedule_revision", flat=True).first()
            or 0
        )
    except Exception:
        return None

    set_cached_schedule_revision_for_school_id(int(school_id), int(new_rev))
    return new_rev


def get_schedule_revision_for_school_id(school_id: int) -> int | None:
    if not school_id:
        return None
    cached = get_cached_schedule_revision_for_school_id(int(school_id))
    if cached is not None:
        return int(cached)
    try:
        rev = int(
            SchoolSettings.objects.filter(school_id=int(school_id)).values_list("schedule_revision", flat=True).first()
            or 0
        )
        set_cached_schedule_revision_for_school_id(int(school_id), int(rev))
        return int(rev)
    except Exception:
        return None


def invalidate_display_snapshot_cache_for_school_id(school_id: int) -> None:
    """Best-effort cache invalidation for display snapshot.

    With revision-aware keys, invalidation is not strictly required for correctness,
    but it helps reclaim memory and avoids any edge cases where clients still carry
    old ETags.
    """

    if not school_id:
        return

    # Delete token caches used by /api/display/status
    try:
        screens = DisplayScreen.objects.filter(school_id=int(school_id)).only("token")
    except Exception:
        screens = []

    for screen in screens:
        token_value = (getattr(screen, "token", "") or "").strip()
        if not token_value:
            continue
        token_hash = sha256(token_value)
        try:
            cache.delete(f"display:snapshot:{token_hash}")
        except Exception:
            pass
        try:
            cache.delete(f"display:token_map:{token_hash}")
        except Exception:
            pass

    # Delete a small window of possible school keys (today +/- 1) across current and previous revisions.
    rev = get_schedule_revision_for_school_id(int(school_id)) or 0
    revs = {rev, max(0, rev - 1), rev + 1}

    try:
        today = timezone.localdate()
    except Exception:
        today = None

    dates = []
    if today:
        dates = [today, today - timedelta(days=1), today + timedelta(days=1)]

    for r in revs:
        try:
            cache.delete(f"snapshot:v5:school:{int(school_id)}:rev:{int(r)}")
        except Exception:
            pass
        for d in dates:
            try:
                cache.delete(f"snapshot:v5:school:{int(school_id)}:rev:{int(r)}:steady:{str(d)}")
            except Exception:
                pass
