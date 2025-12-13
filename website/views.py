# website/views.py
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.models import DisplayScreen
from schedule.models import SchoolSettings

THEME_MAP = {
    "default": "indigo",
    "boys": "emerald",
    "girls": "rose",
    "indigo": "indigo",
    "emerald": "emerald",
    "rose": "rose",
}


def health(request):
    return HttpResponse("School Display is running.")


def _abs_media_url(request, maybe_url: str | None) -> str | None:
    if not maybe_url:
        return None
    s = str(maybe_url).strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        return request.build_absolute_uri(s)
    except Exception:
        return s


def _resolve_screen_and_settings(token: str | None) -> tuple[DisplayScreen | None, SchoolSettings | None, str | None]:
    if not token:
        return None, None, None

    screen = (
        DisplayScreen.objects.select_related("school")
        .filter(token__iexact=token, is_active=True)
        .first()
    )
    if not screen:
        return None, None, None

    try:
        settings_obj = screen.school.schedule_settings
    except SchoolSettings.DoesNotExist:
        return screen, None, token

    return screen, settings_obj, token


def _build_display_context(request, token: str | None) -> dict | None:
    if not token:
        return None

    # ?nocache=1 مفيد أثناء التطوير
    bypass_cache = (request.GET.get("nocache") == "1")

    cache_key = f"display_ctx:{token}"
    if not bypass_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

    screen, settings_obj, effective_token = _resolve_screen_and_settings(token)
    if not screen or not settings_obj:
        return None

    # شعار
    logo_url = None
    if settings_obj.school and getattr(settings_obj.school, "logo", None):
        try:
            logo_url = settings_obj.school.logo.url
        except Exception:
            logo_url = None
    if not logo_url:
        logo_url = getattr(settings_obj, "logo_url", None)
    logo_url = _abs_media_url(request, logo_url)

    raw_theme = getattr(settings_obj, "theme", "default")
    theme = THEME_MAP.get(raw_theme, "indigo")

    school_name = getattr(settings_obj, "name", None) or getattr(settings_obj.school, "name", "مدرستنا")

    ctx = {
        "screen": screen,
        "settings": settings_obj,
        "school_name": school_name,
        "logo_url": logo_url,
        "refresh_interval_sec": getattr(settings_obj, "refresh_interval_sec", 30),
        "standby_scroll_speed": getattr(settings_obj, "standby_scroll_speed", 0.8),
        "periods_scroll_speed": getattr(settings_obj, "periods_scroll_speed", 0.5),
        "now_hour": timezone.localtime().hour,
        "theme": theme,
        "theme_key": raw_theme,
        "api_token": effective_token,
        "display_token": effective_token,
        "token": effective_token,
        "school_id": settings_obj.school_id if settings_obj.school_id else None,
        # مهم: هذا هو المسار الذي يستدعيه display.js
        "snapshot_url": f"/api/display/snapshot/{effective_token}/",
        "firebase_enabled": bool(getattr(settings, "USE_FIREBASE", False)),
    }

    cache.set(cache_key, ctx, 60)
    return ctx


def home(request):
    token = request.GET.get("token") or None
    ctx = _build_display_context(request, token)
    if not ctx:
        return render(request, "website/unconfigured_display.html", {"token": token})
    return render(request, "website/display.html", ctx)


def display(request):
    return home(request)


def display_view(request, screen_key: str):
    if not screen_key:
        raise Http404("Missing screen key.")

    ctx = _build_display_context(request, screen_key)
    if not ctx:
        raise Http404("Display is not configured or found.")

    return render(request, "website/display.html", ctx)
