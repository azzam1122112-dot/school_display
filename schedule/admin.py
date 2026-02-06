# schedule/admin.py
from __future__ import annotations

from django.contrib import admin

from .models import (
    SchoolSettings,
    DutyAssignment,
    SchoolClass,
    Subject,
    Teacher,
    DaySchedule,
    Period,
    Break,
    ClassLesson,
)


# ============================================================
# School Settings
# ============================================================

@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "theme", "featured_panel", "timezone_name", "refresh_interval_sec", "test_mode_weekday_override")
    list_filter = ("theme", "featured_panel", "timezone_name", "test_mode_weekday_override")
    search_fields = ("name", "school__name")
    autocomplete_fields = ("school",)
    ordering = ("name",)
    
    fieldsets = (
        ("معلومات أساسية", {
            "fields": ("school", "name", "logo_url")
        }),
        ("المظهر", {
            "fields": ("theme", "display_accent_color", "featured_panel")
        }),
        ("إعدادات العرض", {
            "fields": ("timezone_name", "refresh_interval_sec", "standby_scroll_speed", "periods_scroll_speed")
        }),
        ("رؤية الأقسام", {
            "fields": (
                "show_home", "show_settings", "show_change_password", "show_screens",
                "show_days", "show_announcements", "show_excellence", "show_standby",
                "show_lessons", "show_school_data"
            ),
            "classes": ("collapse",)
        }),
        ("الإصدارات والتحديثات", {
            "fields": ("schedule_revision",)
        }),
        ("⚠️ وضع الاختبار (للسوبر أدمن فقط)", {
            "fields": ("test_mode_weekday_override",),
            "classes": ("collapse",),
            "description": (
                "<strong style='color: #d97706;'>تحذير:</strong> "
                "هذا الحقل للاختبار فقط. لتشغيل الشاشة في يوم إجازة، حدد اليوم المراد محاكاته. "
                "مثال: لو اليوم خميس (إجازة) وتريد اختبار جدول الأحد، اختر 'الأحد' من القائمة. "
                "<br><strong>لا تنسَ إلغاء التفعيل بعد الاختبار!</strong>"
            )
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        # schedule_revision للقراءة فقط (يتحدث تلقائياً)
        readonly = ["schedule_revision"]
        
        # test_mode_weekday_override للسوبر أدمن فقط
        if not request.user.is_superuser:
            readonly.append("test_mode_weekday_override")
        
        return readonly


@admin.register(DutyAssignment)
class DutyAssignmentAdmin(admin.ModelAdmin):
    list_display = ("date", "school", "teacher_name", "duty_type", "location", "priority", "is_active")
    list_filter = ("date", "duty_type", "is_active")
    search_fields = ("teacher_name", "location", "school__name")
    autocomplete_fields = ("school",)
    ordering = ("-date", "priority", "-id")


# ============================================================
# Core Entities
# ============================================================

@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "settings")
    search_fields = ("name", "settings__name")
    autocomplete_fields = ("settings",)
    list_select_related = ("settings",)
    ordering = ("settings__name", "name")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "school")
    search_fields = ("name", "school__name")
    autocomplete_fields = ("school",)
    list_select_related = ("school",)
    ordering = ("school__name", "name")


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("name", "school")
    search_fields = ("name", "school__name")
    autocomplete_fields = ("school",)
    list_select_related = ("school",)
    ordering = ("school__name", "name")


# ============================================================
# Day Schedule + Inlines
# ============================================================

class PeriodInline(admin.TabularInline):
    model = Period
    extra = 0
    fields = ("index", "starts_at", "ends_at", "school_class", "subject", "teacher")
    autocomplete_fields = ("school_class", "subject", "teacher")
    ordering = ("index", "starts_at")
    show_change_link = True


class BreakInline(admin.TabularInline):
    model = Break
    extra = 0
    fields = ("label", "starts_at", "duration_min")
    ordering = ("starts_at",)
    show_change_link = True


@admin.register(DaySchedule)
class DayScheduleAdmin(admin.ModelAdmin):
    list_display = ("settings", "weekday", "is_active", "periods_count")
    list_filter = ("weekday", "is_active")
    search_fields = ("settings__name", "settings__school__name")
    autocomplete_fields = ("settings",)
    list_select_related = ("settings",)
    ordering = ("settings__name", "weekday")
    inlines = [BreakInline, PeriodInline]


# ============================================================
# Period / Break
# ============================================================

@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ("day", "index", "starts_at", "ends_at", "school_class", "subject", "teacher")
    list_filter = ("day__weekday", "day__settings")
    search_fields = (
        "day__settings__name",
        "day__settings__school__name",
        "school_class__name",
        "subject__name",
        "teacher__name",
    )
    autocomplete_fields = ("day", "school_class", "subject", "teacher")
    list_select_related = ("day", "school_class", "subject", "teacher")
    ordering = ("day__weekday", "index", "starts_at")


@admin.register(Break)
class BreakAdmin(admin.ModelAdmin):
    list_display = ("day", "label", "starts_at", "duration_min")
    list_filter = ("day__weekday", "day__settings")
    search_fields = ("day__settings__name", "day__settings__school__name", "label")
    autocomplete_fields = ("day",)
    list_select_related = ("day",)
    ordering = ("day__weekday", "starts_at")


# ============================================================
# Class Lessons
# ============================================================

@admin.register(ClassLesson)
class ClassLessonAdmin(admin.ModelAdmin):
    list_display = ("settings", "weekday", "period_index", "school_class", "subject", "teacher", "is_active")
    list_filter = ("weekday", "is_active", "settings")
    search_fields = (
        "settings__name",
        "settings__school__name",
        "school_class__name",
        "subject__name",
        "teacher__name",
    )
    autocomplete_fields = ("settings", "school_class", "subject", "teacher")
    list_select_related = ("settings", "school_class", "subject", "teacher")
    ordering = ("settings__name", "weekday", "period_index", "school_class__name")
    