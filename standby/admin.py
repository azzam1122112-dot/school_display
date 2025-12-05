# standby/admin.py
from django.contrib import admin
from .models import StandbyAssignment
from core.admin import SchoolScopedAdmin

@admin.register(StandbyAssignment)
class StandbyAssignmentAdmin(SchoolScopedAdmin):
    list_display = ("date", "school", "period_index", "class_name", "teacher_name")
    list_filter = ("school", "date", "period_index")
    search_fields = ("class_name", "teacher_name")
