from __future__ import annotations

from django.db import migrations


def _migrate_weekday_zero_to_sunday7(apps, schema_editor):
    DaySchedule = apps.get_model("schedule", "DaySchedule")
    Period = apps.get_model("schedule", "Period")
    Break = apps.get_model("schedule", "Break")
    ClassLesson = apps.get_model("schedule", "ClassLesson")

    # DaySchedule: weekday=0 (legacy Sunday) -> weekday=7
    # If a (settings, 7) already exists, we try to merge if target is empty; otherwise drop the legacy day to avoid uniqueness conflicts.
    legacy_days = list(DaySchedule.objects.filter(weekday=0))
    for legacy_day in legacy_days:
        try:
            target_day = DaySchedule.objects.filter(settings_id=legacy_day.settings_id, weekday=7).first()
            if target_day is None:
                legacy_day.weekday = 7
                legacy_day.save(update_fields=["weekday"])
                continue

            target_periods = Period.objects.filter(day_id=target_day.id).exists()
            target_breaks = Break.objects.filter(day_id=target_day.id).exists()

            if not target_periods and not target_breaks:
                Period.objects.filter(day_id=legacy_day.id).update(day_id=target_day.id)
                Break.objects.filter(day_id=legacy_day.id).update(day_id=target_day.id)

            # Remove legacy day (and any remaining related rows) to satisfy unique constraints.
            legacy_day.delete()
        except Exception:
            # If anything goes wrong, do not abort the whole migration.
            # Best-effort: leave the record as-is.
            continue

    # ClassLesson: weekday=0 (legacy Sunday) -> weekday=7
    # Resolve uniqueness conflicts by dropping the legacy duplicate.
    legacy_lessons = list(ClassLesson.objects.filter(weekday=0))
    for lesson in legacy_lessons:
        try:
            conflict = ClassLesson.objects.filter(
                settings_id=lesson.settings_id,
                weekday=7,
                period_index=lesson.period_index,
                school_class_id=lesson.school_class_id,
            ).exists()
            if conflict:
                lesson.delete()
            else:
                lesson.weekday = 7
                lesson.save(update_fields=["weekday"])
        except Exception:
            continue


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0016_add_test_mode_weekday_override"),
    ]

    operations = [
        migrations.RunPython(_migrate_weekday_zero_to_sunday7, migrations.RunPython.noop),
    ]
