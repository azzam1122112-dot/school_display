# schedule/views.py
from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from core.models import School
from schedule.models import SchoolSettings
from .services import get_current_lessons


def api_current_lessons(request, school_id: int):
    school = get_object_or_404(School, pk=school_id)
    settings: SchoolSettings | None = getattr(school, "schedule_settings", None)
    if not settings:
        return JsonResponse({"error": "Schedule settings not configured."}, status=404)

    data = get_current_lessons(settings)
    return JsonResponse(data, safe=False)


def _extract_display_token(settings: SchoolSettings | None) -> str:
    """
    يحاول استخراج توكن العرض من SchoolSettings بدون افتراض اسم حقل محدد.
    """
    if not settings:
        return ""

    for field in ("display_token", "api_token", "token", "public_token", "screen_token"):
        val = getattr(settings, field, "") or ""
        val = str(val).strip()
        if val:
            return val
    return ""


def display_screen(request, school_id: int):
    school = get_object_or_404(School, pk=school_id)
    settings: SchoolSettings | None = getattr(school, "schedule_settings", None)

    settings_theme = "default"
    if settings and settings.theme:
        settings_theme = settings.theme

    theme_map = {
        "default": "indigo",
        "boys": "emerald",
        "girls": "rose",
    }
    theme_slug = theme_map.get(settings_theme, "indigo")

    token = (request.GET.get("token") or "").strip()

    context = {
        "school_id": school.id,
        "school_name": settings.name if settings else school.name,
        "logo_url": settings.logo_url if settings else "",
        "refresh_interval_sec": settings.refresh_interval_sec if settings else 10,
        "standby_scroll_speed": settings.standby_scroll_speed if settings else 0.8,
        "periods_scroll_speed": settings.periods_scroll_speed if settings else 0.5,
        "api_token": token,  # نمرّره للواجهة
        "theme": theme_slug,
    }
    return render(request, "schedule/display.html", context)
