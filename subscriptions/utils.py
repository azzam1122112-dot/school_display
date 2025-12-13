from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .models import SchoolSubscription


def school_has_active_subscription(school_id: int, on_date=None) -> bool:
    today = on_date or timezone.localdate()

    return (
        SchoolSubscription.objects.filter(
            school_id=school_id,
            status="active",
            starts_at__lte=today,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gte=today))
        .exists()
    )
