from django.contrib import admin

from core.models import SubscriptionPlan
from .models import (
    SchoolSubscription,
    SubscriptionInvoice,
    SubscriptionPaymentOperation,
    SubscriptionScreenAddon,
    SubscriptionRequest,
)


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


@admin.register(SubscriptionRequest)
class SubscriptionRequestAdmin(admin.ModelAdmin):
    list_display = (
        "school",
        "request_type",
        "plan",
        "amount",
        "requested_starts_at",
        "status",
        "created_at",
        "processed_by",
    )
    list_filter = ("status", "request_type", "plan")
    search_fields = ("school__name", "school__slug", "transfer_note")
    autocomplete_fields = ("school", "plan", "created_by", "processed_by", "approved_subscription")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("معلومات الطلب", {
            "fields": ("school", "created_by", "request_type", "plan", "requested_starts_at")
        }),
        ("الدفع", {
            "fields": ("amount", "receipt_image", "transfer_note")
        }),
        ("الحالة", {
            "fields": ("status", "admin_note", "processed_by", "processed_at", "approved_subscription")
        }),
        ("التواريخ", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )


@admin.register(SubscriptionPaymentOperation)
class SubscriptionPaymentOperationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "school",
        "plan",
        "amount",
        "method",
        "source",
        "created_by",
        "created_at",
    )
    list_filter = ("method", "source", "created_at")
    search_fields = ("school__name", "plan__name", "created_by__username", "note")
    autocomplete_fields = ("school", "subscription", "plan", "created_by")


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "school",
        "plan",
        "amount",
        "payment_method",
        "issued_at",
        "created_at",
    )
    list_filter = ("payment_method", "currency", "issued_at")
    search_fields = ("invoice_number", "school__name", "plan__name")
    autocomplete_fields = ("school", "subscription", "plan", "operation")
    readonly_fields = ("invoice_number", "created_at")
