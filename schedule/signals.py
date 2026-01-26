from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from schedule.cache_utils import bump_schedule_revision_for_school_id, invalidate_display_snapshot_cache_for_school_id
from schedule.models import Break, ClassLesson, DaySchedule, Period, SchoolSettings

@receiver(post_save, sender=SchoolSettings)
def clear_display_cache_on_settings_change(sender, instance, **kwargs):
    """
    Clears the display context cache for all screens associated with a school
    when its SchoolSettings are updated.
    """
    school_id = int(getattr(instance, "school_id", 0) or 0)
    bump_schedule_revision_for_school_id(school_id)
    invalidate_display_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=DaySchedule)
@receiver(post_delete, sender=DaySchedule)
def clear_display_cache_on_day_schedule_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    bump_schedule_revision_for_school_id(school_id)
    invalidate_display_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=Period)
@receiver(post_delete, sender=Period)
def clear_display_cache_on_period_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    bump_schedule_revision_for_school_id(school_id)
    invalidate_display_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=Break)
@receiver(post_delete, sender=Break)
def clear_display_cache_on_break_change(sender, instance, **kwargs):
    day = getattr(instance, "day", None)
    school_id = int(getattr(getattr(day, "settings", None), "school_id", 0) or 0)
    bump_schedule_revision_for_school_id(school_id)
    invalidate_display_snapshot_cache_for_school_id(school_id)


@receiver(post_save, sender=ClassLesson)
@receiver(post_delete, sender=ClassLesson)
def clear_display_cache_on_class_lesson_change(sender, instance, **kwargs):
    school_id = int(getattr(getattr(instance, "settings", None), "school_id", 0) or 0)
    bump_schedule_revision_for_school_id(school_id)
    invalidate_display_snapshot_cache_for_school_id(school_id)
