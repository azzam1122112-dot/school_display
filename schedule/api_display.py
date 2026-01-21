# schedule/api_display.py
from __future__ import annotations

from typing import Optional

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone

from core.utils import validate_display_token
from schedule.models import DutyAssignment
from schedule.utils import (
    get_today_state,
    get_period_classes_now,
)


@require_GET
def snapshot(request, token: Optional[str] = None):
    """
    Snapshot API – المصدر الوحيد لشاشة العرض
    """

    # 1) التحقق من التوكن (من middleware أو من query/header/Authorization)
    screen, school = validate_display_token(request)

    # 2) لو لم ينجح التحقق، جرّب token القادم من الـ URL
    if (not screen or not school) and token:
        screen, school = validate_display_token(request, token=token)

    if not screen or not school:
        return JsonResponse({"detail": "Forbidden"}, status=403, json_dumps_params={"ensure_ascii": False})

    # 3) إعدادات المدرسة
    settings = getattr(school, "schedule_settings", None)
    if not settings:
        return JsonResponse({"error": "Schedule settings not found."}, status=404, json_dumps_params={"ensure_ascii": False})

    # 4) حالة اليوم (الحصة / الاستراحة / خارج الدوام)
    today_state = get_today_state(school)

    # 5) الحصص الجارية الآن
    period_classes = get_period_classes_now(school)

    # 6) إعدادات العرض
    settings_payload = {
        "theme": getattr(settings, "theme", "default"),
        "featured_panel": getattr(settings, "featured_panel", "excellence"),
        "refresh_interval_sec": getattr(settings, "refresh_interval_sec", 60),
        "standby_scroll_speed": getattr(settings, "standby_scroll_speed", 0.8),
        "periods_scroll_speed": getattr(settings, "periods_scroll_speed", 0.5),
    }

    # 6.5) الإشراف والمناوبة (لليوم الحالي)
    today = timezone.localdate()
    duty_items = (
        DutyAssignment.objects.filter(school=school, date=today, is_active=True)
        .order_by("priority", "-id")
    )
    duty_payload = {
        "items": [obj.as_dict() for obj in duty_items],
    }

    # 7) الـ Payload النهائي (Standard Contract)
    payload = {
        "now": today_state.get("now"),
        "date_info": today_state.get("date_info"),
        "state": today_state.get("state"),
        "current_period": today_state.get("current_period"),
        "next_period": today_state.get("next_period"),
        "day_path": today_state.get("day_path", []),
        "period_classes": period_classes,
        "standby": today_state.get("standby", {"items": []}),
        "excellence": today_state.get("excellence", {"items": []}),
        "duty": duty_payload,
        "settings": settings_payload,
    }

    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
