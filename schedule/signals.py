from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone

from core.models import DisplayScreen

from .api_views import get_cache_key
from .models import Break, ClassLesson, DaySchedule, Period, SchoolSettings


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _invalidate_snapshot_cache_for_school_id(school_id: int) -> None:
    """Hard invalidate all snapshot caches for a school.

    Why: the display endpoints use ETag + cached payloads. Without explicit invalidation,
    the server can keep returning 304 / old JSON for minutes even after the dashboard edits.
    """

    if not school_id:
        return

    # School-wide caches (active window + steady/off-hours)
    try:
        cache.delete(f"snapshot:v4:school:{int(school_id)}")
    except Exception:
        pass

    try:
        today = timezone.localdate()
    except Exception:
        today = None

    if today:
        for d in (today, today + timedelta(days=1), today - timedelta(days=1)):
            try:
                cache.delete(f"snapshot:v4:school:{int(school_id)}:steady:{str(d)}")
            except Exception:
                pass

    # Token caches (used by /api/display/status and /api/display/snapshot)
    try:
        screens = DisplayScreen.objects.filter(school_id=school_id).only("token")
    except Exception:
        screens = []

    for screen in screens:
        token_value = (getattr(screen, "token", "") or "").strip()
        if not token_value:
            continue

        token_hash = _sha256(token_value)
        try:
            cache.delete(get_cache_key(token_hash))
        except Exception:
            pass

        try:
            cache.delete(get_cache_key(token_hash, int(school_id)))
        except Exception:
            pass

        # Legacy/other display caches
        try:
            cache.delete(f"display_context_{token_value}")
        except Exception:
            pass

@receiver(post_save, sender=SchoolSettings)
def clear_display_cache_on_settings_change(sender, instance, **kwargs):
    """
    Clears the display context cache for all screens associated with a school
    when its SchoolSettings are updated.
    """
    school_id = int(getattr(instance, "school_id", 0) or 0)
    if not school_id:
        school = getattr(instance, "school", None)
        school_id = int(getattr(school, "id", 0) or 0)

    _invalidate_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=DaySchedule)
@receiver(post_delete, sender=DaySchedule)
def clear_display_cache_on_day_schedule_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    _invalidate_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=Period)
@receiver(post_delete, sender=Period)
def clear_display_cache_on_period_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    _invalidate_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=Break)
@receiver(post_delete, sender=Break)
def clear_display_cache_on_break_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    _invalidate_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=ClassLesson)
@receiver(post_delete, sender=ClassLesson)
def clear_display_cache_on_class_lesson_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    _invalidate_snapshot_cache_for_school_id(school_id)
