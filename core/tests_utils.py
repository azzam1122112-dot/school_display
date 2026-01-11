from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import secrets
from typing import Any, Optional

from django.apps import apps
from django.utils import timezone


@dataclass(frozen=True)
class ActiveSchoolBundle:
    school: Any
    settings: Any | None
    screen: Any
    subscription: Any | None
    plan: Any | None


def _get_model(*candidates: tuple[str, str]):
    """Return the first existing model among candidates.

    candidates: (app_label, model_name)
    """
    for app_label, model_name in candidates:
        try:
            return apps.get_model(app_label, model_name)
        except Exception:
            continue
    raise LookupError(f"Could not find model in candidates: {candidates!r}")


def _model_has_field(model_cls, field_name: str) -> bool:
    try:
        model_cls._meta.get_field(field_name)
        return True
    except Exception:
        return False


def make_active_school_with_screen(max_screens: int = 3) -> ActiveSchoolBundle:
    """Create a school + (optional) schedule settings + active screen + active subscription.

    هدفها جعل:
    - validate_display_token() ينجح
    - enforce_school_screen_limit() لا يعطّل الشاشة (max_screens >= 1)
    - schedule snapshot يستطيع إيجاد SchoolSettings via school_id
    """
    School = _get_model(("core", "School"))
    DisplayScreen = _get_model(("core", "DisplayScreen"))
    SubscriptionPlan = _get_model(("core", "SubscriptionPlan"))
    SchoolSettings = None
    try:
        SchoolSettings = _get_model(("schedule", "SchoolSettings"))
    except Exception:
        SchoolSettings = None

    # Prefer subscriptions.SchoolSubscription (source of truth), fallback to legacy core.SchoolSubscription.
    SchoolSubscription = _get_model(("subscriptions", "SchoolSubscription"), ("core", "SchoolSubscription"))

    uid = secrets.token_hex(4)

    school = School.objects.create(name=f"Test School {uid}", slug=f"test-school-{uid}")

    settings_obj = None
    if SchoolSettings is not None:
        # schedule snapshot expects settings.school_id to match.
        settings_obj = SchoolSettings.objects.create(
            school=school,
            name=f"Settings {uid}",
            theme=getattr(SchoolSettings, "THEME_DEFAULT", "default"),
        )

    screen = DisplayScreen.objects.create(school=school, name=f"Screen {uid}")
    if _model_has_field(DisplayScreen, "is_active") and not getattr(screen, "is_active", True):
        DisplayScreen.objects.filter(pk=screen.pk).update(is_active=True)
        screen.refresh_from_db()

    plan = SubscriptionPlan.objects.create(
        code=f"plan-{uid}",
        name=f"Plan {uid}",
        max_screens=max(1, int(max_screens)),
    )

    today = timezone.localdate()
    starts_at = today - timedelta(days=1)
    ends_at = today + timedelta(days=30)

    sub_kwargs: dict[str, Any] = {}
    if _model_has_field(SchoolSubscription, "school"):
        sub_kwargs["school"] = school
    if _model_has_field(SchoolSubscription, "plan"):
        sub_kwargs["plan"] = plan

    # Dates
    if _model_has_field(SchoolSubscription, "starts_at"):
        sub_kwargs["starts_at"] = starts_at
    elif _model_has_field(SchoolSubscription, "start_date"):
        sub_kwargs["start_date"] = starts_at

    if _model_has_field(SchoolSubscription, "ends_at"):
        sub_kwargs["ends_at"] = ends_at
    elif _model_has_field(SchoolSubscription, "end_date"):
        sub_kwargs["end_date"] = ends_at

    # Status/flags
    if _model_has_field(SchoolSubscription, "status"):
        sub_kwargs["status"] = "active"
    elif _model_has_field(SchoolSubscription, "is_active"):
        sub_kwargs["is_active"] = True

    subscription = SchoolSubscription.objects.create(**sub_kwargs)

    return ActiveSchoolBundle(
        school=school,
        settings=settings_obj,
        screen=screen,
        subscription=subscription,
        plan=plan,
    )
