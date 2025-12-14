from __future__ import annotations

import logging
from importlib import import_module
from typing import Any, Callable, Dict, List, Tuple, Optional

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: schedule (مرن)
# ---------------------------------------------------------------------------

def _fallback_today_state(_: Any) -> Dict[str, Any]:
    now = timezone.localtime()
    return {
        "state": {"type": "unknown", "label": "لا يوجد جدول لهذا اليوم"},
        "day": {"name": now.strftime("%A"), "date": now.date().isoformat()},
        "periods": [],
        "breaks": [],
        "settings": {},
        "date_info": {"gregorian": now.strftime("%Y-%m-%d")},
    }


def _fallback_period_classes_now(_: Any) -> List[Dict[str, Any]]:
    return []


def _get_schedule_helpers() -> Tuple[
    Callable[[Any], Dict[str, Any]],
    Callable[[Any], List[Dict[str, Any]]],
]:
    """
    يحاول استيراد:
      schedule.utils.get_today_state
      schedule.utils.get_period_classes_now
    وإلا يستخدم fallback بدون كسر الواجهة.
    """
    try:
        utils_mod = import_module("schedule.utils")
    except Exception:
        logger.warning("schedule.utils غير موجود؛ سيتم استخدام fallback.", exc_info=True)
        return _fallback_today_state, _fallback_period_classes_now

    get_today_state = getattr(utils_mod, "get_today_state", None)
    get_period_classes_now = getattr(utils_mod, "get_period_classes_now", None)

    if callable(get_today_state) and callable(get_period_classes_now):
        return get_today_state, get_period_classes_now

    logger.warning(
        "schedule.utils موجود لكن get_today_state/get_period_classes_now غير متاحة؛ fallback."
    )
    return _fallback_today_state, _fallback_period_classes_now


def _safe_list(value: Any) -> List[Dict[str, Any]]:
    """
    يحول أي قيمة إلى List[dict] بشكل آمن (تفادي QuerySet/None/objects غير قابلة للـ JSON).
    """
    if value is None:
        return []
    if isinstance(value, list):
        # تأكد أنها list of dict قدر الإمكان
        out: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
            else:
                out.append({"value": str(item)})
        return out
    try:
        # QuerySet أو iterable
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
            else:
                out.append({"value": str(item)})
        return out
    except Exception:
        return [{"value": str(value)}]


# ---------------------------------------------------------------------------
# notices: Announcement + Excellence (من مشروعك)
# ---------------------------------------------------------------------------

def _get_announcements_for_school(school: Any) -> List[Dict[str, Any]]:
    """
    يعتمد على notices.models.Announcement إن وجد.
    حقولك الشائعة: title, body, level, starts_at, expires_at, is_active, school?
    """
    try:
        from notices.models import Announcement  # type: ignore
    except Exception:
        return []

    now = timezone.localtime()

    try:
        qs = Announcement.objects.all()

        # school filter إن كان موجودًا
        if hasattr(Announcement, "school"):
            qs = qs.filter(school=school)

        # is_active إن كان موجودًا
        if hasattr(Announcement, "is_active"):
            qs = qs.filter(is_active=True)

        # نافذة الزمن إن كانت الحقول موجودة
        if hasattr(Announcement, "starts_at"):
            qs = qs.filter(starts_at__lte=now)
        if hasattr(Announcement, "expires_at"):
            qs = qs.filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))

        qs = qs.order_by("-id")[:20]
    except Exception:
        logger.exception("تعذر جلب الإعلانات.")
        return []

    items: List[Dict[str, Any]] = []
    for a in qs:
        # لو عندك as_dict
        as_dict = getattr(a, "as_dict", None)
        if callable(as_dict):
            try:
                d = as_dict()
                if isinstance(d, dict):
                    items.append(d)
                    continue
            except Exception:
                logger.exception("خطأ في Announcement.as_dict()")

        # fallback: body/text
        body = getattr(a, "body", None)
        if body is None:
            body = getattr(a, "text", "")

        items.append(
            {
                "id": getattr(a, "id", None),
                "title": getattr(a, "title", "") or "",
                "body": body or "",
                "level": getattr(a, "level", "") or "",
            }
        )
    return items


def _get_excellence_items_for_school(school: Any) -> List[Dict[str, Any]]:
    """
    يعتمد على notices.models.Excellence إن وجد.
    حقولك الشائعة: teacher_name, reason, photo, photo_url, start_at, end_at, priority
    """
    try:
        from notices.models import Excellence  # type: ignore
    except Exception:
        return []

    now = timezone.localtime()

    try:
        qs = Excellence.objects.all()
        if hasattr(Excellence, "school"):
            qs = qs.filter(school=school)

        if hasattr(Excellence, "start_at"):
            qs = qs.filter(start_at__lte=now)
        if hasattr(Excellence, "end_at"):
            qs = qs.filter(models.Q(end_at__isnull=True) | models.Q(end_at__gt=now))

        # أولوية إن وجدت
        if hasattr(Excellence, "priority"):
            qs = qs.order_by("-priority", "-id")
        else:
            qs = qs.order_by("-id")

        qs = qs[:30]
    except Exception:
        logger.exception("تعذر جلب المتميزين.")
        return []

    items: List[Dict[str, Any]] = []
    for e in qs:
        photo_url = ""
        try:
            f = getattr(e, "photo", None)
            if f and getattr(f, "url", None):
                photo_url = f.url
        except Exception:
            photo_url = ""

        photo_url = getattr(e, "photo_url", "") or photo_url

        items.append(
            {
                "id": getattr(e, "id", None),
                "name": getattr(e, "teacher_name", "") or "",
                "reason": getattr(e, "reason", "") or "",
                "photo": photo_url or "",
            }
        )
    return items


# ---------------------------------------------------------------------------
# standby: StandbyAssignment (من مشروعك)
# ---------------------------------------------------------------------------

def _get_standby_items_for_school(school: Any) -> List[Dict[str, Any]]:
    """
    في مشروعك الحالي الموديل الظاهر هو: standby.models.StandbyAssignment
    حقول متوقعة: school, date, period_index, class_name, teacher_name, notes
    """
    try:
        from standby.models import StandbyAssignment  # type: ignore
    except Exception:
        return []

    today = timezone.localdate()

    try:
        qs = StandbyAssignment.objects.filter(school=school, date=today).order_by("period_index", "id")
        qs = qs[:50]
    except Exception:
        logger.exception("تعذر جلب حصص الانتظار.")
        return []

    items: List[Dict[str, Any]] = []
    for s in qs:
        items.append(
            {
                "id": getattr(s, "id", None),
                "period_index": getattr(s, "period_index", None),
                "class_name": getattr(s, "class_name", "") or "",
                "teacher_name": getattr(s, "teacher_name", "") or "",
                "notes": getattr(s, "notes", "") or "",
            }
        )
    return items


# ---------------------------------------------------------------------------
# settings for display (SchoolSettings)
# ---------------------------------------------------------------------------

def _get_school_settings_dict(school: Any) -> Dict[str, Any]:
    """
    يجلب SchoolSettings للمدرسة إن وجد.
    """
    try:
        from schedule.models import SchoolSettings  # type: ignore
    except Exception:
        return {}

    try:
        st = SchoolSettings.objects.filter(school=school).select_related("school").first()
        if not st:
            return {}
        return {
            "theme": getattr(st, "theme", "") or "",
            "refresh_interval_sec": getattr(st, "refresh_interval_sec", None),
            "standby_scroll_speed": getattr(st, "standby_scroll_speed", None),
            "periods_scroll_speed": getattr(st, "periods_scroll_speed", None),
        }
    except Exception:
        logger.exception("تعذر جلب SchoolSettings.")
        return {}


# ---------------------------------------------------------------------------
# refresh hint
# ---------------------------------------------------------------------------

def _compute_refresh_hint(today_state: Dict[str, Any], settings_dict: Dict[str, Any]) -> int:
    """
    - إن كانت المدرسة محددة refresh_interval_sec نرجّعها (إن كانت رقمًا صالحًا)
    - وإلا نحسب تلميح حسب حالة اليوم
    """
    try:
        v = settings_dict.get("refresh_interval_sec")
        if isinstance(v, int) and v >= 5:
            return v
    except Exception:
        pass

    state = today_state.get("state") or {}
    state_type = (state.get("type") or "").lower().strip()

    if state_type in {"before", "period", "break"}:
        return 10
    if state_type == "after":
        return 30 * 60
    if state_type == "off":
        return 180 * 60
    return 60


# ---------------------------------------------------------------------------
# build payload (Schema ثابت + مفاتيح احتياطية)
# ---------------------------------------------------------------------------

def _build_snapshot_payload(school: Any) -> Dict[str, Any]:
    get_today_state, get_period_classes_now = _get_schedule_helpers()

    today_state: Dict[str, Any] = {}
    try:
        today_state = get_today_state(school) or {}
    except Exception:
        logger.exception("get_today_state فشل؛ fallback.")
        today_state = _fallback_today_state(school)

    period_classes_raw: Any
    try:
        period_classes_raw = get_period_classes_now(school)
    except Exception:
        logger.exception("get_period_classes_now فشل؛ fallback.")
        period_classes_raw = []

    period_classes = _safe_list(period_classes_raw)

    ann_items = _get_announcements_for_school(school)
    standby_items = _get_standby_items_for_school(school)
    exc_items = _get_excellence_items_for_school(school)

    settings_dict = _get_school_settings_dict(school)
    refresh_hint_seconds = _compute_refresh_hint(today_state, settings_dict)

    payload: Dict[str, Any] = {
        "schema_version": 2,
        "school": {
            "id": getattr(school, "id", None),
            "name": getattr(school, "name", "") or "",
            "slug": getattr(school, "slug", "") or "",
            "logo": (getattr(getattr(school, "logo", None), "url", "") or ""),
        },
        "today": today_state,
        "period_classes": period_classes,
        "ann": ann_items,
        "standby": {"items": standby_items},
        "exc": {"items": exc_items},
        "settings": settings_dict,
        "server_time": timezone.now().isoformat(),
        "refresh_hint_seconds": int(refresh_hint_seconds),
        # مفاتيح احتياطية (لو display.js قديم)
        "announcements": ann_items,
        "standby_items": standby_items,
        "excellence_items": exc_items,
    }
    return payload


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

@require_GET
def display_snapshot(request: HttpRequest, token: Optional[str] = None) -> HttpResponse:
    """
    ✅ Snapshot API لشاشة العرض.

    يعمل بطريقتين:
    1) الأفضل: token ضمن الـURL (/api/display/snapshot/<token>/)
       → يجلب DisplayScreen + school ويحدّث last_seen.
    2) بديل: request.school من middleware (إن كان موجودًا)

    كاش: 10 ثواني لكل (school + date).
    Debug: ?debug=1 يضيف diagnostics
    """

    school = None
    screen = None

    # 1) من token إن توفر
    if token:
        try:
            from core.models import DisplayScreen  # type: ignore
            screen = (
                DisplayScreen.objects.select_related("school")
                .filter(token=token, is_active=True)
                .first()
            )
            if not screen or not getattr(screen, "school", None):
                return JsonResponse({"error": "Invalid token or inactive screen."}, status=404)

            school = screen.school

            # تحديث last_seen إن كان موجودًا
            try:
                if hasattr(screen, "last_seen"):
                    screen.last_seen = timezone.now()
                    screen.save(update_fields=["last_seen"])
                elif hasattr(screen, "last_seen_at"):
                    screen.last_seen_at = timezone.now()
                    screen.save(update_fields=["last_seen_at"])
            except Exception:
                # لا نفشل الـAPI بسبب last_seen
                logger.debug("تعذر تحديث last_seen للشاشة.", exc_info=True)

        except Exception:
            logger.exception("تعذر resolve token إلى DisplayScreen.")
            return JsonResponse({"error": "Server error while resolving token."}, status=500)

    # 2) fallback من middleware
    if school is None:
        school = getattr(request, "school", None)

    if school is None:
        return JsonResponse(
            {
                "error": "Missing school context. Provide token in URL or enable middleware to inject request.school."
            },
            status=400,
        )

    today = timezone.localdate()
    cache_key = f"display:snapshot:{getattr(school, 'id', 'unknown')}:{today.isoformat()}"

    cached = cache.get(cache_key)
    if cached is not None:
        cached = dict(cached)
        cached["server_time"] = timezone.now().isoformat()

        # Debug info
        if request.GET.get("debug"):
            cached["debug"] = {
                "source": "cache",
                "school_id": getattr(school, "id", None),
                "token_used": bool(token),
            }
        return JsonResponse(cached)

    data = _build_snapshot_payload(school)
    cache.set(cache_key, data, timeout=10)

    if request.GET.get("debug"):
        data = dict(data)
        data["debug"] = {
            "source": "fresh",
            "school_id": getattr(school, "id", None),
            "token_used": bool(token),
            "server_local": timezone.localtime().isoformat(),
            "keys": sorted(list(data.keys())),
        }

    return JsonResponse(data)


# Django ORM Q import (داخل الملف لتجنب لبس في أعلى الملف)
from django.db import models  # noqa: E402
