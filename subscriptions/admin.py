from django.contrib import admin

from core.models import SubscriptionPlan
from .models import SchoolSubscription, SubscriptionScreenAddon


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


@admin.register(SubscriptionScreenAddon)
class SubscriptionScreenAddonAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "screens_added",
        "pricing_cycle",
        "validity_days",
        "pricing_strategy",
        "bundle_price",
        "unit_price",
        "proration_factor",
        "total_price",
        "starts_at",
        "ends_at",
        "status",
    )
    list_filter = ("status",)
    search_fields = ("subscription__school__name", "subscription__school__slug")
    autocomplete_fields = ("subscription",)
