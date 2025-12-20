from __future__ import annotations

from core.models import SupportTicket


def admin_support_ticket_badges(request):
    """Global template context: admin-only support ticket badges.

    "New" tickets are interpreted as tickets with status == "open".
    """

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_superuser", False):
        return {}

    return {
        "admin_new_support_tickets_count": SupportTicket.objects.filter(status="open").count(),
    }
