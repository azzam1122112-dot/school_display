from __future__ import annotations

from django.apps import apps
from django.urls import reverse

from core.models import SupportTicket


def _is_active_link(current_url_name: str, *, exact: tuple[str, ...] = (), startswith: tuple[str, ...] = ()) -> bool:
    name = (current_url_name or "").strip()
    if not name:
        return False
    if exact and name in exact:
        return True
    if startswith:
        for prefix in startswith:
            if name.startswith(prefix):
                return True
    return False


def _build_admin_nav_links(
    *,
    current_url_name: str,
    is_support_staff: bool,
    open_subscription_requests_count: int,
    open_support_tickets_count: int,
):
    """Single source of truth for SaaS admin navigation + dashboard action cards."""

    base_items = [
        {
            "key": "home",
            "title": "الرئيسية",
            "description": "نظرة عامة على النظام والإحصائيات",
            "url_name": "dashboard:system_admin_dashboard",
            "icon": "fa-home",
            "emoji": "🏠",
            "tone": "slate",
            "exact": ("system_admin_dashboard",),
            "startswith": (),
            "visible": True,
            "badge_count": 0,
        },
        {
            "key": "schools",
            "title": "إدارة المدارس",
            "description": "إضافة وتعديل وإدارة المدارس",
            "url_name": "dashboard:system_schools_list",
            "icon": "fa-building",
            "emoji": "🏫",
            "tone": "blue",
            "exact": (),
            "startswith": ("system_school",),
            "visible": not is_support_staff,
            "badge_count": 0,
        },
        {
            "key": "users",
            "title": "إدارة المستخدمين",
            "description": "إدارة الحسابات والصلاحيات",
            "url_name": "dashboard:system_users_list",
            "icon": "fa-user-circle",
            "emoji": "👤",
            "tone": "purple",
            "exact": (),
            "startswith": ("system_user",),
            "visible": True,
            "badge_count": 0,
        },
        {
            "key": "employees",
            "title": "إدارة الموظفين",
            "description": "إدارة موظفي النظام وصلاحياتهم",
            "url_name": "dashboard:system_employees_list",
            "icon": "fa-user-tie",
            "emoji": "🧑‍💼",
            "tone": "sky",
            "exact": ("system_employees_list",),
            "startswith": (),
            "visible": True,
            "badge_count": 0,
        },
        {
            "key": "subscriptions",
            "title": "إدارة الاشتراكات",
            "description": "متابعة الاشتراكات والخطط النشطة",
            "url_name": "dashboard:system_subscriptions_list",
            "icon": "fa-file-invoice-dollar",
            "emoji": "💳",
            "tone": "emerald",
            "exact": (),
            "startswith": ("system_subscription",),
            "visible": True,
            "badge_count": 0,
        },
        {
            "key": "subscription_requests",
            "title": "طلبات التجديد/الاشتراك",
            "description": "استعراض الطلبات واعتمادها أو رفضها",
            "url_name": "dashboard:system_subscription_requests_list",
            "icon": "fa-receipt",
            "emoji": "🧾",
            "tone": "rose",
            "exact": (),
            "startswith": ("system_subscription_request",),
            "visible": True,
            "badge_count": int(open_subscription_requests_count or 0),
        },
        {
            "key": "reports",
            "title": "التقارير والإحصائيات",
            "description": "تقارير الأداء والإيرادات والنمو",
            "url_name": "dashboard:system_reports",
            "icon": "fa-chart-line",
            "emoji": "📊",
            "tone": "amber",
            "exact": ("system_reports",),
            "startswith": (),
            "visible": True,
            "badge_count": 0,
        },
        {
            "key": "support",
            "title": "تذاكر الدعم",
            "description": "متابعة طلبات الدعم الفني",
            "url_name": "dashboard:system_support_tickets",
            "icon": "fa-headset",
            "emoji": "🛟",
            "tone": "rose",
            "exact": (),
            "startswith": ("system_support",),
            "visible": True,
            "badge_count": int(open_support_tickets_count or 0),
        },
    ]

    links = []
    for item in base_items:
        if not item.get("visible", True):
            continue

        resolved = {
            "key": item["key"],
            "title": item["title"],
            "description": item["description"],
            "icon": item["icon"],
            "emoji": item["emoji"],
            "tone": item["tone"],
            "url": reverse(item["url_name"]),
            "active": _is_active_link(
                current_url_name,
                exact=tuple(item.get("exact", ()) or ()),
                startswith=tuple(item.get("startswith", ()) or ()),
            ),
            "badge_count": int(item.get("badge_count") or 0),
        }

        if resolved["key"] == "subscriptions":
            if (current_url_name or "").startswith("system_subscription_request"):
                resolved["active"] = False

        links.append(resolved)

    return links


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

    open_support_tickets_count = SupportTicket.objects.filter(status="open").count()
    counts = {
        "is_system_staff": True,
        "is_support_staff": bool(is_support),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "admin_new_support_tickets_count": open_support_tickets_count,
    }

    # Subscription requests (best-effort: feature may not exist in older DBs)
    open_subscription_requests_count = 0
    try:
        Req = apps.get_model("subscriptions", "SubscriptionRequest")
        open_subscription_requests_count = Req.objects.filter(
            status__in=["submitted", "under_review"]
        ).count()
    except Exception:
        open_subscription_requests_count = 0

    counts["admin_open_subscription_requests_count"] = int(open_subscription_requests_count or 0)

    current_url_name = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    counts["admin_nav_links"] = _build_admin_nav_links(
        current_url_name=current_url_name,
        is_support_staff=bool(is_support),
        open_subscription_requests_count=int(open_subscription_requests_count or 0),
        open_support_tickets_count=int(open_support_tickets_count or 0),
    )

    return counts
