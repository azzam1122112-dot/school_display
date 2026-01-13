from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.models import DisplayScreen
from schedule.models import SchoolSettings


THEME_MAP = {
    # legacy
    "default": "indigo",
    "boys": "emerald",
    "girls": "rose",

    # current
    "indigo": "indigo",
    "emerald": "emerald",
    "rose": "rose",
    "cyan": "cyan",
    "amber": "amber",
    "orange": "orange",
    "violet": "violet",
}


def health(request):
    return HttpResponse("School Display is running.")


def _abs_media_url(request, maybe_url: str | None) -> str | None:
    if not maybe_url:
        return None
    s = str(maybe_url).strip()
    if s.lower() in {"none", "null", "-"}:
        return None
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        return request.build_absolute_uri(s)
    except Exception:
        return s


def _resolve_screen_and_settings(
    key: str | None,
) -> tuple[DisplayScreen | None, SchoolSettings | None, str | None]:
    """
    key قد يكون:
    - token طويل (64)
    - أو short_code قصير (مثل 6)
    نُرجع دائمًا effective_token = screen.token حتى تعتمد الواجهة والـ API على token الحقيقي.
    """
    if not key:
        return None, None, None

    k = str(key).strip()
    if not k:
        return None, None, None

    screen = (
        DisplayScreen.objects.select_related("school")
        .filter(is_active=True)
        .filter(Q(token__iexact=k) | Q(short_code__iexact=k))
        .first()
    )
    if not screen:
        return None, None, None

    try:
        settings_obj = screen.school.schedule_settings
    except SchoolSettings.DoesNotExist:
        # نرجع token الحقيقي حتى لو الإعدادات ناقصة
        return screen, None, screen.token

    return screen, settings_obj, screen.token


def _build_display_context(request, key: str | None) -> dict | None:
    if not key:
        return None

    # ?nocache=1 مفيد أثناء التطوير
    bypass_cache = (request.GET.get("nocache") == "1")

    screen, settings_obj, effective_token = _resolve_screen_and_settings(key)
    if not screen or not settings_obj or not effective_token:
        return None

    # ✅ الكاش يعتمد على token الحقيقي للشاشة دائمًا (حتى لو دخلت بـ short_code)
    cache_key = f"display_ctx:{effective_token}"
    if not bypass_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

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
    school_type = getattr(settings_obj.school, "school_type", "") if getattr(settings_obj, "school", None) else ""
    display_accent_color = getattr(settings_obj, "display_accent_color", None)

    ctx = {
        "screen": screen,
        "settings": settings_obj,
        "school_name": school_name,
        "school_type": school_type,
        "display_accent_color": display_accent_color,
        "logo_url": logo_url,
        "refresh_interval_sec": getattr(settings_obj, "refresh_interval_sec", 30),
        "standby_scroll_speed": getattr(settings_obj, "standby_scroll_speed", 0.8),
        "periods_scroll_speed": getattr(settings_obj, "periods_scroll_speed", 0.5),
        "now_hour": timezone.localtime().hour,
        "theme": theme,
        "theme_key": raw_theme,
        # ✅ نعطي الواجهة token الحقيقي دائمًا
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
    """
    الصفحة الرئيسية للشاشة:
    /?token=XXXX
    token قد يكون token طويل أو short_code بعد التحديث.
    """
    key = request.GET.get("token") or None
    ctx = _build_display_context(request, key)
    if not ctx:
        return render(request, "website/unconfigured_display.html", {"token": key})
    return render(request, "website/display.html", ctx)


def subscriptions(request):
    return render(request, "website/subscriptions.html")


def display(request):
    return home(request)


def display_view(request, screen_key: str):
    """
    /display/<screen_key> (اختياري)
    screen_key قد يكون token أو short_code.
    """
    if not screen_key:
        raise Http404("Missing screen key.")

    ctx = _build_display_context(request, screen_key)
    if not ctx:
        raise Http404("Display is not configured or found.")

    return render(request, "website/display.html", ctx)


def short_display_redirect(request, short_code: str):
    """
    ✅ الرابط المختصر: /s/<short_code> أو /s/<short_code>/
    بعد التحديث لا نعمل redirect للرابط الطويل،
    بل نعرض الشاشة مباشرة (أفضل للتلفاز وأسهل للمستخدم).
    """
    code = (short_code or "").strip()
    if not code:
        raise Http404("Invalid short code.")
    return display_view(request, code)
