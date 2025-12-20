from __future__ import annotations

from django.apps import apps
from django.db.models import Q


def enforce_school_screen_limit(school_id: int) -> None:
    """Enforce screen limit by auto-disabling newest screens above limit.

    Policy:
    - Keep the oldest screens (created_at/id) up to the current effective limit.
    - Auto-disable the newest screens beyond the limit.
    - When the limit increases again, auto-reenable previously auto-disabled screens
      (without touching screens that were manually disabled).

    "New" here means status == open for tickets; unrelated. Here, "newest" means latest created.
    """

    if not school_id:
        return

    # Late import to avoid hard coupling.
    try:
        from subscriptions.utils import school_effective_max_screens
    except Exception:
        return

    limit = school_effective_max_screens(school_id)

    DisplayScreen = apps.get_model("core", "DisplayScreen")

    # Unlimited: re-enable all auto-disabled screens.
    if limit is None:
        DisplayScreen.objects.filter(school_id=school_id, auto_disabled_by_limit=True).update(
            is_active=True,
            auto_disabled_by_limit=False,
        )
        return

    try:
        limit_int = int(limit)
    except Exception:
        return

    if limit_int < 0:
        return

    # Candidates are screens that are either active or were auto-disabled previously.
    # Manual inactive screens (is_active=False and auto_disabled_by_limit=False) are ignored.
    candidate_ids = list(
        DisplayScreen.objects.filter(school_id=school_id)
        .filter(Q(is_active=True) | Q(auto_disabled_by_limit=True))
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )

    if len(candidate_ids) <= limit_int:
        # We are under the limit: re-enable any auto-disabled screens.
        DisplayScreen.objects.filter(school_id=school_id, auto_disabled_by_limit=True).update(
            is_active=True,
            auto_disabled_by_limit=False,
        )
        return

    keep_ids = set(candidate_ids[:limit_int])
    disable_ids = set(candidate_ids[limit_int:])

    # Re-enable screens that were auto-disabled but should now be within the limit.
    DisplayScreen.objects.filter(id__in=keep_ids, auto_disabled_by_limit=True).update(
        is_active=True,
        auto_disabled_by_limit=False,
    )

    # Disable screens beyond limit (only those currently active so we don't touch manual inactive).
    DisplayScreen.objects.filter(id__in=disable_ids, is_active=True).update(
        is_active=False,
        auto_disabled_by_limit=True,
    )
