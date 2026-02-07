import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from schedule.cache_utils import (
    bump_schedule_revision_for_school_id_debounced,
    get_schedule_revision_for_school_id,
    invalidate_display_snapshot_cache_for_school_id,
)
from schedule.models import Break, ClassLesson, DaySchedule, Period, SchoolSettings

logger = logging.getLogger(__name__)


def _broadcast_invalidate_ws(school_id: int, revision: int) -> None:
    """
    Broadcast invalidate message to WebSocket clients (async via channel layer).
    
    Called from transaction.on_commit() to ensure DB commit before notification.
    Only runs if DISPLAY_WS_ENABLED=True.
    """
    from django.conf import settings
    if not getattr(settings, "DISPLAY_WS_ENABLED", False):
        return
    
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer
        
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        
        group_name = f"school:{school_id}"
        
        # Broadcast to all clients in school group
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_invalidate",  # maps to DisplayConsumer.broadcast_invalidate
                "school_id": school_id,
                "revision": revision,
            }
        )
        
        logger.info(
            f"WS broadcast sent: group={group_name} revision={revision}"
        )
    except Exception as e:
        # Never crash signals due to WS errors
        logger.exception(f"WS broadcast failed school_id={school_id}: {e}")


def _bump_and_invalidate(*, school_id: int, reason: str, model_label: str) -> None:
    """Source-of-truth invalidation.

    schedule_revision MUST bump on any change that can affect the display snapshot.

    Snapshot data sources (must be covered by signals):
    - schedule.SchoolSettings (theme/settings/display flags)
    - schedule.DaySchedule / schedule.Period / schedule.Break (timetable)
    - schedule.ClassLesson (period_classes overlay)
    - schedule.DutyAssignment (duty panel)
    - notices.Announcement (announcements ribbon)
    - notices.Excellence (honor/excellence board)
    - standby.StandbyAssignment (standby/waiting list)
    - core.School (name/logo/media that appears in snapshot.settings)
    """

    school_id = int(school_id or 0)
    if not school_id:
        return

    old_rev = get_schedule_revision_for_school_id(school_id) or 0
    did_bump = bump_schedule_revision_for_school_id_debounced(school_id=school_id)

    if not did_bump:
        logger.info(
            "schedule_revision debounce skip school_id=%s reason=%s model=%s",
            school_id,
            reason,
            model_label,
        )
        return

    new_rev = get_schedule_revision_for_school_id(school_id) or 0
    invalidate_display_snapshot_cache_for_school_id(school_id)

    logger.info(
        "schedule_revision bumped school_id=%s old_rev=%s new_rev=%s reason=%s model=%s",
        school_id,
        int(old_rev),
        int(new_rev),
        reason,
        model_label,
    )
    
    # Broadcast to WebSocket clients (after transaction commits)
    transaction.on_commit(lambda: _broadcast_invalidate_ws(school_id, new_rev))

@receiver(post_save, sender=SchoolSettings)
def clear_display_cache_on_settings_change(sender, instance, **kwargs):
    """
    Clears the display context cache for all screens associated with a school
    when its SchoolSettings are updated.
    """
    school_id = int(getattr(instance, "school_id", 0) or 0)
    _bump_and_invalidate(school_id=school_id, reason="post_save", model_label="schedule.SchoolSettings")


@receiver(post_save, sender=DaySchedule)
@receiver(post_delete, sender=DaySchedule)
def clear_display_cache_on_day_schedule_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.DaySchedule")


@receiver(post_save, sender=Period)
@receiver(post_delete, sender=Period)
def clear_display_cache_on_period_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.Period")


@receiver(post_save, sender=Break)
@receiver(post_delete, sender=Break)
def clear_display_cache_on_break_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.Break")


@receiver(post_save, sender=ClassLesson)
@receiver(post_delete, sender=ClassLesson)
def clear_display_cache_on_class_lesson_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.ClassLesson")


# -----------------------------
# Core entities that affect snapshot rendering
# -----------------------------

try:
    from schedule.models import SchoolClass

    @receiver(post_save, sender=SchoolClass)
    @receiver(post_delete, sender=SchoolClass)
    def clear_display_cache_on_school_class_change(sender, instance, **kwargs):
        settings_obj = getattr(instance, "settings", None)
        school_id = int(getattr(settings_obj, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.SchoolClass")
except Exception:
    SchoolClass = None


try:
    from schedule.models import Subject

    @receiver(post_save, sender=Subject)
    @receiver(post_delete, sender=Subject)
    def clear_display_cache_on_subject_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.Subject")
except Exception:
    Subject = None


try:
    from schedule.models import Teacher

    @receiver(post_save, sender=Teacher)
    @receiver(post_delete, sender=Teacher)
    def clear_display_cache_on_teacher_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.Teacher")
except Exception:
    Teacher = None


# -----------------------------
# Additional snapshot sources
# -----------------------------

try:
    from schedule.models import DutyAssignment

    @receiver(post_save, sender=DutyAssignment)
    @receiver(post_delete, sender=DutyAssignment)
    def clear_display_cache_on_duty_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="schedule.DutyAssignment")
except Exception:
    DutyAssignment = None


try:
    from notices.models import Announcement, Excellence

    @receiver(post_save, sender=Announcement)
    @receiver(post_delete, sender=Announcement)
    def clear_display_cache_on_announcement_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="notices.Announcement")

    @receiver(post_save, sender=Excellence)
    @receiver(post_delete, sender=Excellence)
    def clear_display_cache_on_excellence_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="notices.Excellence")
except Exception:
    Announcement = None
    Excellence = None


try:
    from standby.models import StandbyAssignment

    @receiver(post_save, sender=StandbyAssignment)
    @receiver(post_delete, sender=StandbyAssignment)
    def clear_display_cache_on_standby_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "school_id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason=sender.__name__, model_label="standby.StandbyAssignment")
except Exception:
    StandbyAssignment = None


try:
    from core.models import School

    @receiver(post_save, sender=School)
    def clear_display_cache_on_school_change(sender, instance, **kwargs):
        school_id = int(getattr(instance, "id", 0) or 0)
        _bump_and_invalidate(school_id=school_id, reason="post_save", model_label="core.School")
except Exception:
    School = None
