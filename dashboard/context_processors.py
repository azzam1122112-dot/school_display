from __future__ import annotations

from django.apps import apps

from core.models import SupportTicket


def admin_support_ticket_badges(request):
    """Global template context: admin-only support ticket badges.

    "New" tickets are interpreted as tickets with status == "open".
    """

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    try:
        is_support = user.groups.filter(name="Support").exists()
    except Exception:
        is_support = False

    is_system_staff = bool(getattr(user, "is_superuser", False) or is_support)
    if not is_system_staff:
        return {}

    counts = {
        "is_system_staff": True,
        "is_support_staff": bool(is_support),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "admin_new_support_tickets_count": SupportTicket.objects.filter(status="open").count(),
    }

    # Subscription requests (best-effort: feature may not exist in older DBs)
    try:
        Req = apps.get_model("subscriptions", "SubscriptionRequest")
        counts["admin_open_subscription_requests_count"] = Req.objects.filter(
            status__in=["submitted", "under_review"]
        ).count()
    except Exception:
        pass

    return counts
