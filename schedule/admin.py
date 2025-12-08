from django.contrib import admin
from .models import (
    SchoolSettings,
    SchoolClass,
    Subject,
    Teacher,
    DaySchedule,
    Period,
    Break,
    ClassLesson,
)
from core.admin import SchoolScopedAdmin


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(SchoolScopedAdmin):
    list_display = (
        "name", "school", "timezone_name", "refresh_interval_sec",
        "show_home", "show_settings", "show_change_password", "show_screens", "show_days",
        "show_announcements", "show_excellence", "show_standby", "show_lessons", "show_school_data"
    )
    search_fields = ("name",)


@admin.register(SchoolClass)
class SchoolClassAdmin(SchoolScopedAdmin):
    list_display = ("name", "settings")
    list_filter = ("settings",)
    search_fields = ("name",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


class PeriodInline(admin.TabularInline):
    model = Period
    extra = 0
    fields = ("index", "starts_at", "ends_at", "school_class", "subject", "teacher")
    ordering = ("index",)


class BreakInline(admin.TabularInline):
    model = Break
    extra = 0
    fields = ("label", "starts_at", "duration_min")
    ordering = ("starts_at",)


@admin.register(DaySchedule)
class DayScheduleAdmin(SchoolScopedAdmin):
    list_display = ("settings", "weekday", "periods_count", "is_active")
    list_filter = ("settings", "weekday", "is_active")
    inlines = [PeriodInline, BreakInline]


@admin.register(ClassLesson)
class ClassLessonAdmin(SchoolScopedAdmin):
    list_display = (
        "settings",
        "weekday",
        "period_index",
        "school_class",
        "subject",
        "teacher",
        "is_active",
    )
    list_filter = (
        "settings",
        "weekday",
        "period_index",
        "school_class",
        "teacher",
        "is_active",
    )
    search_fields = (
        "school_class__name",
        "subject__name",
        "teacher__name",
    )
    ordering = (
        "settings",
        "weekday",
        "period_index",
        "school_class__name",
    )
