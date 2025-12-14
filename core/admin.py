# core/admin.py
from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

from .models import School, DisplayScreen, UserProfile


class SchoolScopedAdmin(admin.ModelAdmin):
    """
    Mixin to restrict admin view to the user's active_school.
    Superusers see everything.
    """

    def _get_active_school(self, request):
        profile = getattr(request.user, "profile", None)
        return getattr(profile, "active_school", None)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs

        school = self._get_active_school(request)
        if not school:
            return qs.none()

        # Model has direct 'school'
        if hasattr(self.model, "school"):
            return qs.filter(school=school)

        # Model has 'settings' -> settings.school
        if hasattr(self.model, "settings"):
            return qs.filter(settings__school=school)

        return qs.none()

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            school = self._get_active_school(request)
            if school and hasattr(obj, "school"):
                obj.school = school
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            school = self._get_active_school(request)
            if school:
                if db_field.name == "school":
                    kwargs["queryset"] = School.objects.filter(id=school.id)
                elif db_field.name == "settings":
                    # For DaySchedule -> SchoolSettings (avoid circular import at module level)
                    from schedule.models import SchoolSettings
                    kwargs["queryset"] = SchoolSettings.objects.filter(school=school)

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    list_filter = ("is_active",)
    ordering = ("name",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """
    ✅ Updated for:
      - active_school (FK)
      - schools (M2M)
    """

    list_display = ("user", "active_school", "schools_count")
    list_filter = ("active_school", "schools")
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "active_school__name",
        "schools__name",
    )
    autocomplete_fields = ("user", "active_school", "schools")
    list_select_related = ("active_school",)

    @admin.display(description="عدد المدارس")
    def schools_count(self, obj: UserProfile) -> int:
        try:
            return obj.schools.count()
        except Exception:
            return 0


@admin.register(DisplayScreen)
class DisplayScreenAdmin(SchoolScopedAdmin):
    """
    DisplayScreen admin:
    - token is read-only
    - supports last_seen_at OR last_seen (legacy) automatically
    """

    list_display = ("name", "school", "is_active", "last_seen_display")
    list_filter = ("school", "is_active")
    search_fields = ("name", "token")
    autocomplete_fields = ("school",)
    list_select_related = ("school",)

    def _has_field(self, field_name: str) -> bool:
        try:
            DisplayScreen._meta.get_field(field_name)
            return True
        except Exception:
            return False

    def get_readonly_fields(self, request, obj=None):
        ro = ["token"]
        # اجعل حقول آخر اتصال للقراءة فقط إن كانت موجودة
        if self._has_field("last_seen_at"):
            ro.append("last_seen_at")
        if self._has_field("last_seen"):
            ro.append("last_seen")
        if self._has_field("created_at"):
            ro.append("created_at")
        return tuple(ro)

    @admin.display(description="آخر اتصال")
    def last_seen_display(self, obj):
        if self._has_field("last_seen_at"):
            val = getattr(obj, "last_seen_at", None)
        else:
            val = getattr(obj, "last_seen", None)

        if not val:
            return "—"

        # عرض لطيف + آمن
        try:
            return timezone.localtime(val).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(val)
