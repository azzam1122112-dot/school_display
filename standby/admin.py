# standby/admin.py
from django.contrib import admin
from .models import StandbyAssignment

@admin.register(StandbyAssignment)
class StandbyAssignmentAdmin(admin.ModelAdmin):
    list_display = ("date", "period_index", "class_name", "teacher_name")
    list_filter = ("date", "period_index")
    search_fields = ("class_name", "teacher_name")
