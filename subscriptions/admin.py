from django.contrib import admin

from core.models import SubscriptionPlan
from .models import SchoolSubscription


# إدارة خطط الاشتراك
@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    """
    Admin بسيط لعرض خطط الاشتراك الموجودة في core.SubscriptionPlan
    بدون افتراض أي حقول غير مضمونة.
    """
    list_display = ("id", "name", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active",)


# إدارة اشتراكات المدارس
@admin.register(SchoolSubscription)
class SchoolSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("school", "plan", "starts_at", "ends_at", "status", "is_active")
    list_filter = ("status", "plan")
    search_fields = ("school__name", "school__slug")
    autocomplete_fields = ("school", "plan")
