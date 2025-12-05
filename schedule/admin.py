# schedule/admin.py
from django.contrib import admin
from .models import SchoolSettings, DaySchedule, Period, Break
from core.admin import SchoolScopedAdmin

@admin.register(SchoolSettings)
class SchoolSettingsAdmin(SchoolScopedAdmin):
    list_display = ("name", "school", "timezone_name", "refresh_interval_sec")
    search_fields = ("name",)

class PeriodInline(admin.TabularInline):
    model = Period
    extra = 0
    fields = ("index", "starts_at", "ends_at")
    ordering = ("index",)

class BreakInline(admin.TabularInline):
    model = Break
    extra = 0
    fields = ("label", "starts_at", "duration_min")
    ordering = ("starts_at",)

@admin.register(DaySchedule)
class DayScheduleAdmin(SchoolScopedAdmin):
    list_display = ("settings", "weekday", "periods_count")
    list_filter = ("settings", "weekday")
    inlines = [PeriodInline, BreakInline]
