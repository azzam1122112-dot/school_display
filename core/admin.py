from django.contrib import admin
from .models import School, DisplayScreen, UserProfile

class SchoolScopedAdmin(admin.ModelAdmin):
    """
    Mixin to restrict admin view to the user's school.
    Superusers see everything.
    """
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if hasattr(request.user, 'profile') and request.user.profile.school:
            # Check if the model has a 'school' field
            if hasattr(self.model, 'school'):
                return qs.filter(school=request.user.profile.school)
            # Special case for DaySchedule which links to SchoolSettings
            if hasattr(self.model, 'settings'):
                return qs.filter(settings__school=request.user.profile.school)
        return qs.none()

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if hasattr(request.user, 'profile') and request.user.profile.school:
                if hasattr(obj, 'school'):
                    obj.school = request.user.profile.school
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser and hasattr(request.user, 'profile') and request.user.profile.school:
            if db_field.name == "school":
                kwargs["queryset"] = School.objects.filter(id=request.user.profile.school.id)
            elif db_field.name == "settings":
                 # For DaySchedule -> SchoolSettings
                 from schedule.models import SchoolSettings
                 kwargs["queryset"] = SchoolSettings.objects.filter(school=request.user.profile.school)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'school')
    list_filter = ('school',)
    search_fields = ('user__username', 'user__email', 'school__name')

@admin.register(DisplayScreen)
class DisplayScreenAdmin(SchoolScopedAdmin):
    list_display = ('name', 'school', 'is_active', 'last_seen')
    list_filter = ('school', 'is_active')
    search_fields = ('name', 'token')
    readonly_fields = ('token', 'last_seen')
