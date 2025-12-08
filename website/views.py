from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import DisplayScreen
from schedule.models import ClassLesson, Period, SchoolSettings

# خريطة تحويل كود الثيم في الإعدادات → كود الثيم في الواجهة
THEME_MAP = {
    # القيم الجديدة في SchoolSettings.theme
    "default": "indigo",   # افتراضي
    "boys": "emerald",     # مدارس البنين
    "girls": "rose",       # مدارس البنات

    # دعم خلفي للقيم القديمة (لو بقيت سجلات قديمة في قاعدة البيانات)
    "indigo": "indigo",
    "emerald": "emerald",
    "rose": "rose",
}


def health(request):
    return HttpResponse("School Display is running.")


def _resolve_screen_and_settings(token: str | None) -> tuple[DisplayScreen | None, SchoolSettings | None, str | None]:
    settings_obj = None
    effective_token = token or None
    screen = None

    if effective_token:
        try:
            screen = (
                DisplayScreen.objects
                .select_related("school")
                .get(token=effective_token, is_active=True)
            )
            settings_obj = (
                SchoolSettings.objects
                .filter(school=screen.school)
                .first()
            )
        except DisplayScreen.DoesNotExist:
            screen = None
            settings_obj = None

    if settings_obj is None:
        settings_obj = (
            SchoolSettings.objects
            .select_related("school")
            .filter(school__isnull=False)
            .first()
        )
        if settings_obj and not effective_token:
            screen = (
                DisplayScreen.objects
                .filter(school=settings_obj.school, is_active=True)
                .first()
            )
            if screen:
                effective_token = screen.token

    return screen, settings_obj, effective_token


def _build_display_context(token: str | None) -> dict:
    screen, settings_obj, effective_token = _resolve_screen_and_settings(token)

    # --- الشعار ---
    logo_url = None
    if settings_obj:
        if settings_obj.school and getattr(settings_obj.school, "logo", None):
            logo_url = settings_obj.school.logo.url
        else:
            logo_url = getattr(settings_obj, "logo_url", None)

    # قيم افتراضية
    default_refresh_interval = 30
    default_standby_speed = 0.8
    default_periods_speed = 0.5

    # اسم المدرسة
    school_name = "مدرستنا"
    if settings_obj and getattr(settings_obj, "name", None):
        school_name = settings_obj.name

    # فاصل التحديث
    refresh_interval_sec = default_refresh_interval
    if settings_obj and getattr(settings_obj, "refresh_interval_sec", None) is not None:
        refresh_interval_sec = settings_obj.refresh_interval_sec

    # سرعة تمرير الانتظار
    standby_scroll_speed = default_standby_speed
    if settings_obj and getattr(settings_obj, "standby_scroll_speed", None) is not None:
        standby_scroll_speed = settings_obj.standby_scroll_speed

    # سرعة تمرير جدول الحصص
    periods_scroll_speed = default_periods_speed
    if settings_obj and getattr(settings_obj, "periods_scroll_speed", None) is not None:
        periods_scroll_speed = settings_obj.periods_scroll_speed

    # ⚠️ أهم جزء: تحويل الكود المخزن في الإعدادات إلى كود الثيم في الواجهة
    raw_theme = "default"
    if settings_obj and getattr(settings_obj, "theme", None):
        raw_theme = settings_obj.theme

    theme = THEME_MAP.get(raw_theme, "indigo")

    school_id = None
    if settings_obj and getattr(settings_obj, "school", None):
        school_id = settings_obj.school.id

    ctx = {
        "screen": screen,
        "settings": settings_obj,
        "school_name": school_name,
        "logo_url": logo_url,
        "refresh_interval_sec": refresh_interval_sec,
        "standby_scroll_speed": standby_scroll_speed,
        "periods_scroll_speed": periods_scroll_speed,
        "now_hour": timezone.localtime().hour,
        "theme": theme,
        "api_token": effective_token,
        "school_id": school_id,
        "firebase_enabled": getattr(settings, "USE_FIREBASE", False),
    }
    return ctx


def display(request):
    return home(request)


def home(request):
    token = request.GET.get("token") or None
    ctx = _build_display_context(token)
    return render(request, "website/display.html", ctx)


def display_view(request, screen_key: str):
    if not screen_key:
        raise Http404("Missing screen key.")
    ctx = _build_display_context(screen_key)
    if ctx.get("settings") is None:
        raise Http404("Display is not configured.")
    return render(request, "website/display.html", ctx)


def current_period_live(request, screen_key: str):
    if not screen_key:
        raise Http404("Missing screen key.")

    try:
        screen = (
            DisplayScreen.objects
            .select_related("school")
            .get(token=screen_key, is_active=True)
        )
    except DisplayScreen.DoesNotExist:
        raise Http404("Screen not found.")

    settings_obj = (
        SchoolSettings.objects
        .filter(school=screen.school)
        .first()
    )
    if settings_obj is None:
        raise Http404("School settings not found.")

    today = timezone.localdate()
    now = timezone.localtime()
    now_time = now.time()

    python_weekday = today.weekday()
    weekday = (python_weekday + 1) % 7

    periods_qs = (
        Period.objects
        .filter(day__settings=settings_obj, day__weekday=weekday)
        .order_by("index")
    )

    current_period = None
    for p in periods_qs:
        if not p.starts_at or not p.ends_at:
            continue
        if p.starts_at <= now_time < p.ends_at:
            current_period = p
            break

    current_lessons = []
    if current_period is not None:
        current_lessons = (
            ClassLesson.objects
            .filter(
                settings=settings_obj,
                weekday=weekday,
                period_index=current_period.index,
                is_active=True,
            )
            .select_related("school_class", "subject", "teacher")
            .order_by("school_class__name")
        )

    context = {
        "screen": screen,
        "settings": settings_obj,
        "today": today,
        "now": now,
        "current_period": current_period,
        "current_lessons": current_lessons,
    }
    return render(request, "website/current_period_live.html", context)
