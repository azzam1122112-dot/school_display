# schedule/api_views.py
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import time
from datetime import time as dt_time
from typing import Iterable, Optional

from django.conf import settings as dj_settings
from django.core.cache import cache
from django.db import models
from django.db.models import Q
from django.http import JsonResponse, HttpResponseNotModified
from django.utils import timezone
from django.views.decorators.http import require_GET

from core.models import School, DisplayScreen
from schedule.models import SchoolSettings, ClassLesson, Period
from schedule.time_engine import build_day_snapshot

logger = logging.getLogger(__name__)


def _metrics_interval_seconds() -> int:
    # Log cache hit/miss metrics at INFO at most once per N seconds.
    # Keep it conservative to avoid log noise in SaaS.
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC", os.getenv("DISPLAY_SNAPSHOT_CACHE_METRICS_INTERVAL_SEC", "600")))
    except Exception:
        v = 600
    return max(60, min(3600, v))

def _metrics_incr(key: str) -> None:
    try:
        cache.incr(key)
    except Exception:
        try:
            cache.add(key, 1, timeout=60 * 60 * 24)
        except Exception:
            pass


def _metrics_add(key: str, delta: int) -> None:
    try:
        cache.incr(key, int(delta))
    except Exception:
        try:
            cur = cache.get(key) or 0
            cache.set(key, int(cur) + int(delta), timeout=60 * 60 * 24)
        except Exception:
            pass


def _metrics_set_max(key: str, value: int) -> None:
    try:
        cur = cache.get(key)
        cur_i = int(cur) if cur is not None else 0
        v = int(value)
        if v > cur_i:
            cache.set(key, v, timeout=60 * 60 * 24)
    except Exception:
        pass

def _metrics_log_maybe() -> None:
    interval = _metrics_interval_seconds()
    throttle_key = f"metrics:snapshot_cache:log:{interval}"
    try:
        should_log = bool(cache.add(throttle_key, "1", timeout=interval))
    except Exception:
        should_log = False

    if not should_log:
        return

    keys = [
        "metrics:snapshot_cache:token_hit",
        "metrics:snapshot_cache:token_miss",
        "metrics:snapshot_cache:school_hit",
        "metrics:snapshot_cache:school_miss",
        "metrics:snapshot_cache:steady_hit",
        "metrics:snapshot_cache:steady_miss",
        "metrics:snapshot_cache:build_count",
        "metrics:snapshot_cache:build_sum_ms",
        "metrics:snapshot_cache:build_max_ms",
    ]
    try:
        vals = {k: (cache.get(k) or 0) for k in keys}
    except Exception:
        vals = {k: 0 for k in keys}

    build_count = int(vals.get(keys[6], 0) or 0)
    build_sum_ms = int(vals.get(keys[7], 0) or 0)
    build_max_ms = int(vals.get(keys[8], 0) or 0)
    build_avg_ms = int(build_sum_ms / build_count) if build_count > 0 else 0

    logger.info(
        "snapshot_cache metrics token_hit=%s token_miss=%s school_hit=%s school_miss=%s steady_hit=%s steady_miss=%s build_count=%s build_avg_ms=%s build_max_ms=%s",
        vals.get(keys[0], 0),
        vals.get(keys[1], 0),
        vals.get(keys[2], 0),
        vals.get(keys[3], 0),
        vals.get(keys[4], 0),
        vals.get(keys[5], 0),
        build_count,
        build_avg_ms,
        build_max_ms,
    )


def _snapshot_ttl_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_TTL", 10) or 10)
    except Exception:
        v = 10
    return max(1, min(60, v))


def _snapshot_build_lock_ttl_seconds() -> int:
    # Short lock to coalesce concurrent requests.
    return 8


def _snapshot_bind_ttl_seconds() -> int:
    # How long a token stays bound to the first seen device_key.
    return 60 * 60 * 24 * 30  # 30 days


def _stable_json_bytes(payload: dict) -> bytes:
    # Stable encoding for ETag hashing (order-independent).
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _etag_from_json_bytes(json_bytes: bytes) -> str:
    return hashlib.sha256(json_bytes).hexdigest()


def _parse_if_none_match(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    # We only support a single strong ETag value.
    if s.startswith("W/"):
        s = s[2:].strip()
    if s.startswith('"') and s.endswith('"') and len(s) > 1:
        s = s[1:-1]
    if not s:
        return None
    return s


def _snapshot_anti_loop_check(token_hash: str) -> bool:
    """
    Checks if a token is requesting too frequently (looping).
    Returns True if safe, False if looping (should receive cool-down).
    Limit: 30 requests per minute.
    """
    key = f"loop:{token_hash}"
    try:
        # 60 seconds rolling window (approx)
        added = cache.add(key, 1, timeout=60)
        if added:
            val = 1
        else:
            val = cache.incr(key)
        
        if val > 30: 
            return False
        return True
    except Exception:
        return True


def _snapshot_rate_limit_allow(token_hash: str, device_hash: str) -> bool:
    """Token bucket: 1 req/sec with burst 3, keyed by token_hash + device_hash."""

    capacity = 3.0
    refill_per_sec = 1.0
    state_key = f"rl:snapshot:{token_hash}:{device_hash}"
    lock_key = f"{state_key}:lock"

    now = time.monotonic()
    state = None

    have_lock = False
    try:
        have_lock = bool(cache.add(lock_key, "1", timeout=1))
    except Exception:
        have_lock = False

    if not have_lock:
        # Best effort: if we can't lock, avoid hard-failing the request.
        return True

    try:
        state = cache.get(state_key)
        if not isinstance(state, dict):
            state = {"tokens": capacity, "ts": now}

        tokens = float(state.get("tokens", capacity))
        last_ts = float(state.get("ts", now))

        elapsed = max(0.0, now - last_ts)
        tokens = min(capacity, tokens + elapsed * refill_per_sec)

        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0

        state = {"tokens": tokens, "ts": now}
        try:
            cache.set(state_key, state, timeout=60)
        except Exception:
            pass

        return allowed
    finally:
        try:
            cache.delete(lock_key)
        except Exception:
            pass


def _app_revision() -> str:
    try:
        v = str(getattr(dj_settings, "APP_REVISION", "") or "").strip()
    except Exception:
        v = ""
    return v


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        for k in ("items", "results", "data", "rows", "list"):
            v = value.get(k)
            if isinstance(v, list):
                return v
    return []


def _normalize_snapshot_keys(snap: dict) -> dict:
    """
    مفاتيح ثابتة للواجهة:
      - announcements
      - excellence
      - standby
      - period_classes
      - day_path
    """
    if not isinstance(snap, dict):
        return {
            "settings": {},
            "state": {},
            "day_path": [],
            "current_period": None,
            "next_period": None,
            "period_classes": [],
            "standby": [],
            "excellence": [],
            "announcements": [],
        }

    for container_key in ("data", "payload", "result", "snapshot"):
        c = snap.get(container_key)
        if isinstance(c, dict):
            for k, v in c.items():
                snap.setdefault(k, v)

    def fill(dst_key: str, source_keys):
        cur = _as_list(snap.get(dst_key))
        if cur:
            snap[dst_key] = cur
            return
        for k in source_keys:
            arr = _as_list(snap.get(k))
            if arr:
                snap[dst_key] = arr
                return
        snap[dst_key] = []

    fill(
        "excellence",
        ["honor_board", "excellence_board", "honors", "awards", "excellent", "excellent_students", "honor_items"],
    )
    fill(
        "standby",
        ["waiting", "standby_periods", "standby_items", "standby_list", "standbyClasses", "standby_classes"],
    )
    fill(
        "announcements",
        ["alerts", "notices", "messages", "announcement_list", "announcements_list"],
    )

    snap["day_path"] = _as_list(snap.get("day_path"))
    snap["period_classes"] = _as_list(snap.get("period_classes"))
    return snap


def _fallback_payload(message: str = "إعدادات المدرسة غير مهيأة") -> dict:
    now = timezone.localtime()
    return {
        "now": now.isoformat(),
        "meta": {"weekday": now.isoweekday()},
        "settings": {
            "name": "",
            "logo_url": None,
            "theme": "indigo",
            "refresh_interval_sec": 10,
            "standby_scroll_speed": 0.8,
            "periods_scroll_speed": 0.5,
        },
        "state": {
            "type": "config",
            "label": message,
            "from": None,
            "to": None,
            "remaining_seconds": 0,
        },
        "day_path": [],
        "current_period": None,
        "next_period": None,
        "period_classes": [],
        "standby": [],
        "excellence": [],
        "announcements": [],
    }


def _extract_token(request, token_from_path: str | None) -> str | None:
    t = (token_from_path or "").strip()

    # Fallback: some callers may embed token in the URL path while not passing it
    # via query/header (or if the URL pattern changes). Parse it from the path.
    if not t:
        try:
            p = (getattr(request, "path_info", "") or getattr(request, "path", "") or "").strip()
            m = re.search(r"/api/display/(?:snapshot|today|live|status)/([^/]+)/?$", p, flags=re.IGNORECASE)
            if m and m.group(1):
                t = (m.group(1) or "").strip()
        except Exception:
            pass

    if not t:
        t = (request.headers.get("X-Display-Token") or "").strip()
    if not t:
        t = (request.GET.get("token") or "").strip()
    if not t or len(t) < 8 or len(t) > 256:
        return None
    return t


@require_GET
def status(request, token: str | None = None):
    """Lightweight polling endpoint.

    GET /api/display/status/?token=...   (or X-Display-Token header)
    GET /api/display/status/<token>/

    Behavior:
    - If we have a cached snapshot entry for this token, return 304 when If-None-Match matches.
    - Otherwise return a small JSON telling the client to fetch snapshot.

    This endpoint never builds snapshots and should stay cheap.
    """
    token_value = _extract_token(request, token)
    if not token_value:
        try:
            p = (getattr(request, "path_info", "") or getattr(request, "path", "") or "").strip()
            logger.warning("status: invalid_token path=%s", p)
        except Exception:
            pass
        return JsonResponse({"detail": "invalid_token"}, status=403)

    token_hash = _sha256(token_value)
    cache_key = get_cache_key(token_hash)

    cached_entry = cache.get(cache_key)
    if isinstance(cached_entry, dict) and isinstance(cached_entry.get("etag"), str):
        inm = _parse_if_none_match(request.headers.get("If-None-Match"))
        etag = cached_entry.get("etag")
        if inm and etag and inm == etag:
            resp = HttpResponseNotModified()
            resp["ETag"] = f"\"{etag}\""
            resp["Cache-Control"] = "no-store"
            resp["Vary"] = "Accept-Encoding"
            return resp

        return JsonResponse({"fetch_required": True, "etag": etag}, json_dumps_params={"ensure_ascii": False})

    return JsonResponse({"fetch_required": True}, json_dumps_params={"ensure_ascii": False})


def _is_hex_sha256(token_value: str) -> bool:
    if not token_value or len(token_value) != 64:
        return False
    try:
        int(token_value, 16)
        return True
    except Exception:
        return False


def _candidate_fields_for_model(model_cls) -> list[str]:
    keywords = ("token", "key", "api", "secret", "hash", "code", "slug")
    fields: list[str] = []
    for f in model_cls._meta.fields:
        if isinstance(f, (models.CharField, models.TextField)):
            n = f.name.lower()
            if any(k in n for k in keywords):
                fields.append(f.name)
    return fields


def _get_settings_by_school_id(school_id: int) -> SchoolSettings | None:
    return (
        SchoolSettings.objects.select_related("school")
        .filter(school_id=school_id)
        .first()
    )


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _token_variants_for_school_ids(school_id: int) -> Iterable[str]:
    secret = getattr(dj_settings, "DISPLAY_TOKEN_SALT", "") or dj_settings.SECRET_KEY
    sid = str(school_id)
    patterns = [
        f"{sid}:{secret}",
        f"{secret}:{sid}",
        f"display:{sid}:{secret}",
        f"{sid}{secret}",
        f"{secret}{sid}",
    ]
    for p in patterns:
        yield _sha256(p)


def _match_settings_by_hash_token(token_value: str) -> SchoolSettings | None:
    if not _is_hex_sha256(token_value):
        return None

    qs = SchoolSettings.objects.select_related("school").only("id", "school_id")
    for ss in qs:
        for v in _token_variants_for_school_ids(ss.school_id):
            if v == token_value:
                return SchoolSettings.objects.select_related("school").get(pk=ss.pk)
    return None


def _get_settings_by_token(token_value: str) -> SchoolSettings | None:
    if not token_value:
        return None

    ss_fields = _candidate_fields_for_model(SchoolSettings)
    if ss_fields:
        q = Q()
        for name in ss_fields:
            q |= Q(**{name: token_value})
        obj = SchoolSettings.objects.select_related("school").filter(q).first()
        if obj:
            return obj

    s_fields = _candidate_fields_for_model(School)
    if s_fields:
        q = Q()
        for name in s_fields:
            q |= Q(**{name: token_value})
        school = School.objects.filter(q).first()
        if school:
            return _get_settings_by_school_id(school.id)

    obj = _match_settings_by_hash_token(token_value)
    if obj:
        return obj

    return None


def _abs_media_url(request, maybe_url: str | None) -> str | None:
    if not maybe_url:
        return None
    s = str(maybe_url).strip()
    if s.lower() in {"none", "null", "-"}:
        return None
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s.replace("http://", "//").replace("https://", "//")
    try:
        return request.build_absolute_uri(s)
    except Exception:
        return s


def _model_has_field(model_cls, field_name: str) -> bool:
    try:
        model_cls._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _get_active_screens_qs():
    qs = DisplayScreen.objects.all()
    if _model_has_field(DisplayScreen, "is_active"):
        qs = qs.filter(is_active=True)
    return qs.select_related("school")


def _match_settings_via_display_screen(token_value: str) -> Optional[SchoolSettings]:
    if not token_value:
        return None

    only_fields = ["id", "school_id"]
    if _model_has_field(DisplayScreen, "token"):
        only_fields.append("token")

    qs = _get_active_screens_qs().only(*only_fields)

    if _model_has_field(DisplayScreen, "token"):
        screen = qs.filter(token__iexact=token_value).first()
        if screen:
            return _get_settings_by_school_id(screen.school_id)

    if _is_hex_sha256(token_value) and _model_has_field(DisplayScreen, "token"):
        for s in qs:
            try:
                if _sha256(s.token) == token_value:
                    return _get_settings_by_school_id(s.school_id)
            except Exception:
                continue

    return None


def _parse_hhmm(value: str | None) -> dt_time | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        parts = s.split(":")
        if len(parts) == 2:
            h, m = int(parts[0]), int(parts[1])
            return dt_time(hour=h, minute=m)
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            return dt_time(hour=h, minute=m, second=sec)
    except Exception:
        return None
    return None


def _infer_period_index(settings_obj: SchoolSettings, weekday: int, current_period: dict | None) -> int | None:
    if not current_period:
        return None

    idx = current_period.get("index")
    try:
        if idx is not None:
            idx_int = int(idx)
            if idx_int > 0:
                return idx_int
    except Exception:
        pass

    t_from = _parse_hhmm(current_period.get("from"))
    t_to = _parse_hhmm(current_period.get("to"))
    if not t_from or not t_to:
        return None

    try:
        return (
            Period.objects
            .filter(
                day__settings=settings_obj,
                day__weekday=weekday,
                starts_at=t_from,
                ends_at=t_to,
            )
            .values_list("index", flat=True)
            .first()
        )
    except Exception:
        return None


def _build_period_classes(settings_obj: SchoolSettings, weekday: int, period_index: int) -> list[dict]:
    qs = (
        ClassLesson.objects
        .filter(settings=settings_obj, weekday=weekday, period_index=period_index, is_active=True)
        .select_related("school_class", "subject", "teacher")
        .order_by("school_class__name")
    )
    items: list[dict] = []
    for cl in qs:
        items.append({
            "class": getattr(cl.school_class, "name", "") or "",
            "subject": getattr(cl.subject, "name", "") or "",
            "teacher": getattr(cl.teacher, "name", "") or "",
            "period_index": cl.period_index,
            "weekday": cl.weekday,
        })
    return items


def _normalize_theme_value(raw: str | None) -> str:
    """
    SchoolSettings.theme عندك: default/boys/girls
    شاشة العرض/CSS: indigo/emerald/rose
    """
    v = (raw or "").strip().lower()
    if not v:
        return "indigo"

    if v in ("indigo", "emerald", "rose", "cyan", "amber", "orange", "violet"):
        return v

    if v in ("default", "theme_default"):
        return "indigo"
    if v in ("boys", "theme_boys"):
        return "emerald"
    if v in ("girls", "theme_girls"):
        return "rose"

    return "indigo"


def _merge_real_data_into_snapshot(request, snap: dict, settings_obj: SchoolSettings):
    """
    ✅ دمج بيانات المدرسة الحقيقية داخل snapshot:
    - announcements  (notices.Announcement)
    - excellence     (notices.Excellence)
    - standby        (standby.StandbyAssignment)
    - duty           (schedule.DutyAssignment)
    """
    school = getattr(settings_obj, "school", None)
    if not school:
        return

    # -----------------------------
    # Announcements
    # -----------------------------
    try:
        from notices.models import Announcement  # type: ignore

        qs = Announcement.objects.active_for_school(school, now=timezone.now())

        order = []
        if _model_has_field(Announcement, "priority"):
            order.append("-priority")
        if _model_has_field(Announcement, "starts_at"):
            order.append("-starts_at")
        order.append("-id")
        qs = qs.order_by(*order)[:10]

        items = []
        for a in qs:
            d = a.as_dict() if hasattr(a, "as_dict") else {
                "title": getattr(a, "title", "") or "",
                "body": getattr(a, "body", "") or "",
                "level": getattr(a, "level", "") or "info",
            }
            title = (d.get("title") or "").strip()
            body = (d.get("body") or "").strip()
            if title and body:
                d["message"] = f"{title}\n{body}"
            else:
                d["message"] = title or body or "تنبيه"
            items.append(d)

        snap["announcements"] = items

    except Exception:
        logger.exception("snapshot: failed to merge announcements")

    # -----------------------------
    # Excellence (Honor Board)
    # -----------------------------
    try:
        from notices.models import Excellence  # type: ignore

        qs = Excellence.active_for_today(school) if hasattr(Excellence, "active_for_today") else Excellence.objects.filter(school=school)
        qs = qs[:30]

        items = []
        for e in qs:
            d = e.as_dict() if hasattr(e, "as_dict") else {
                "name": getattr(e, "teacher_name", "") or getattr(e, "name", "") or "",
                "reason": getattr(e, "reason", "") or "",
                "photo_url": getattr(e, "photo_url", None),
            }
            for k in ("image", "image_url", "photo_url"):
                if d.get(k):
                    d[k] = _abs_media_url(request, d.get(k))
            items.append(d)

        snap["excellence"] = items

    except Exception:
        logger.exception("snapshot: failed to merge excellence")

    # -----------------------------
    # Standby assignments
    # -----------------------------
    try:
        from standby.models import StandbyAssignment  # type: ignore

        today = timezone.localdate()
        qs = StandbyAssignment.objects.filter(school=school, date=today).order_by("period_index", "id")

        items = []
        for s in qs:
            items.append({
                "period_index": getattr(s, "period_index", None),
                "class_name": getattr(s, "class_name", "") or "",
                "teacher_name": getattr(s, "teacher_name", "") or "",
                "notes": getattr(s, "notes", "") or "",
            })

        snap["standby"] = items

    except Exception:
        logger.exception("snapshot: failed to merge standby")

    # -----------------------------
    # Duty / Supervision
    # -----------------------------
    try:
        from schedule.models import DutyAssignment  # type: ignore

        today = timezone.localdate()
        qs = (
            DutyAssignment.objects.filter(school=school, date=today, is_active=True)
            .order_by("priority", "-id")
        )

        snap["duty"] = {"items": [obj.as_dict() if hasattr(obj, "as_dict") else {
            "id": getattr(obj, "id", None),
            "date": getattr(obj, "date", None).isoformat() if getattr(obj, "date", None) else None,
            "teacher_name": getattr(obj, "teacher_name", "") or "",
            "duty_type": getattr(obj, "duty_type", "") or "",
            "duty_label": getattr(obj, "get_duty_type_display", lambda: "")() if hasattr(obj, "get_duty_type_display") else "",
            "location": getattr(obj, "location", "") or "",
        } for obj in qs]}

    except Exception:
        logger.exception("snapshot: failed to merge duty")


@require_GET
def ping(request):
    now = timezone.localtime()
    return JsonResponse({"ok": True, "now": now.isoformat()}, json_dumps_params={"ensure_ascii": False})


def _call_build_day_snapshot(settings_obj: SchoolSettings) -> dict:
    now = timezone.localtime()
    try:
        return build_day_snapshot(settings_obj, now=now)
    except TypeError:
        try:
            school = getattr(settings_obj, "school", None)
            if school:
                return build_day_snapshot(school=school, for_date=now.date())
        except Exception:
            pass
        return build_day_snapshot(settings_obj)


def _is_missing_index(d: dict) -> bool:
    if "index" not in d:
        return True
    v = d.get("index")
    return v is None or v == "" or v == 0

def _snapshot_cache_key(settings_obj: SchoolSettings) -> str:
    school_id = int(getattr(settings_obj, "school_id", None) or 0)
    return f"snapshot:v1:school:{school_id}"


def _snapshot_cache_ttl_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_CACHE_TTL", 15) or 15)
    except Exception:
        v = 15
    return max(5, min(30, v))


def _active_window_cache_ttl_seconds() -> int:
    """Cache TTL during active window: hard clamp to 15–20 seconds (Phase 2)."""
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_ACTIVE_TTL", 15) or 15)
    except Exception:
        v = 15
    return max(15, min(20, v))

def _steady_snapshot_cache_ttl_seconds(day_snap: dict) -> int:
    """Outside active window/holidays: long TTL, aligned to refresh_interval_sec when available."""
    try:
        s = (day_snap.get("settings") or {}) if isinstance(day_snap, dict) else {}
        refresh = int(s.get("refresh_interval_sec") or 3600)
    except Exception:
        refresh = 3600
    # Very long, but bounded (default 20 minutes to prevent carrying over 'Off' state to next day).
    try:
        max_ttl = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_STEADY_MAX_TTL", 1200) or 1200)
    except Exception:
        max_ttl = 1200
    # Allow env to override up to 24h, but default logic caps at 1200s (20m)
    max_ttl = max(300, min(86400, max_ttl))
    return max(300, min(max_ttl, refresh))

def _is_active_window(day_snap: dict) -> bool:
    try:
        meta = day_snap.get("meta") or {}
        return bool(meta.get("is_active_window"))
    except Exception:
        return False

def _steady_snapshot_cache_key(settings_obj: SchoolSettings, day_snap: dict) -> str:
    school_id = int(getattr(settings_obj, "school_id", None) or 0)
    # isolate by local date from snapshot meta to avoid cross-day bleed.
    date_str = None
    try:
        date_str = (day_snap.get("meta") or {}).get("date")
    except Exception:
        date_str = None
    if not date_str:
        date_str = str(timezone.localdate())
    return f"snapshot:v2:school:{school_id}:steady:{date_str}"


def get_cache_key(token_hash: str, school_id: int | None = None) -> str:
    """Tenant-safe snapshot cache key.

    If tokens are globally unique, token_hash alone is enough.
    We still include school_id whenever we have it, to avoid accidental collisions.
    """
    if school_id:
        return f"display:snapshot:{int(school_id)}:{token_hash}"
    return f"display:snapshot:{token_hash}"


def compute_dynamic_ttl_seconds(day_snap: dict) -> int:
    if _is_active_window(day_snap):
        return _active_window_cache_ttl_seconds()
    return _steady_snapshot_cache_ttl_seconds(day_snap)


def build_steady_snapshot(
    request,
    settings_obj: SchoolSettings,
    *,
    steady_state: str,
    refresh_interval_sec: int,
    label: str,
) -> dict:
    """Build a UI-safe steady snapshot (no expensive merges/queries).

    Required invariants:
    - never returns {}
    - includes expected arrays/keys
    - explicit state types for off-hours / no schedule
    """
    now = timezone.localtime()
    school = getattr(settings_obj, "school", None)

    school_name = ""
    if school is not None:
        school_name = getattr(school, "name", "") or ""
    if not school_name:
        school_name = getattr(settings_obj, "name", "") or ""

    logo = getattr(settings_obj, "logo_url", None)
    if not logo and school is not None:
        for attr in ("logo_url", "logo", "logo_image", "logo_file"):
            if hasattr(school, attr):
                val = getattr(school, attr)
                try:
                    logo = val.url
                except Exception:
                    logo = val
                if logo:
                    break

    return {
        "now": now.isoformat(),
        "meta": {
            "date": str(now.date()),
            "weekday": ((now.date().weekday() + 1) % 7),
            "is_school_day": steady_state != "NO_SCHEDULE_TODAY",
            "is_active_window": False,
            "active_window": None,
        },
        "settings": {
            "name": school_name,
            "logo_url": _abs_media_url(request, logo),
            "theme": _normalize_theme_value(getattr(settings_obj, "theme", None)),
            "refresh_interval_sec": int(refresh_interval_sec),
            "standby_scroll_speed": float(getattr(settings_obj, "standby_scroll_speed", 0.8) or 0.8),
            "periods_scroll_speed": float(getattr(settings_obj, "periods_scroll_speed", 0.5) or 0.5),
        },
        "state": {
            "type": steady_state,
            "label": label,
            "from": None,
            "to": None,
            "remaining_seconds": 0,
        },
        "day_path": [],
        "current_period": None,
        "next_period": None,
        "period_classes": [],
        "standby": [],
        "excellence": [],
        "duty": {"items": []},
        "announcements": [],
    }


def _snapshot_edge_cache_max_age_seconds() -> int:
    try:
        v = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_EDGE_MAX_AGE", 10) or 10)
    except Exception:
        v = 10
    return max(1, min(60, v))

def _build_final_snapshot(
    request,
    settings_obj: SchoolSettings,
    *,
    day_snap: dict | None = None,
    merge_real_data: bool = True,
) -> dict:
    snap = day_snap if isinstance(day_snap, dict) else _call_build_day_snapshot(settings_obj)
    snap = _normalize_snapshot_keys(snap)

    # مفاتيح أساسية
    snap.setdefault("meta", {})
    snap.setdefault("settings", {})
    snap.setdefault("state", {})
    snap.setdefault("day_path", [])
    snap.setdefault("current_period", None)
    snap.setdefault("next_period", None)
    snap.setdefault("period_classes", [])
    snap.setdefault("standby", [])
    snap.setdefault("excellence", [])
    snap.setdefault("duty", {"items": []})
    snap.setdefault("announcements", [])

    # settings unify + theme mapping
    s = snap["settings"] or {}
    school = getattr(settings_obj, "school", None)

    school_name = ""
    if school is not None:
        school_name = getattr(school, "name", "") or ""
    if not school_name:
        school_name = getattr(settings_obj, "name", "") or ""

    if school_name and not s.get("name"):
        s["name"] = school_name

    logo = s.get("logo_url") or getattr(settings_obj, "logo_url", None)
    if not logo and school is not None:
        for attr in ("logo_url", "logo", "logo_image", "logo_file"):
            if hasattr(school, attr):
                val = getattr(school, attr)
                try:
                    logo = val.url
                except Exception:
                    logo = val
                if logo:
                    break
    s["logo_url"] = _abs_media_url(request, logo)

    # ✅ الثيم: تحويل default/boys/girls -> indigo/emerald/rose
    s["theme"] = _normalize_theme_value(getattr(settings_obj, "theme", None) or s.get("theme"))

    # ✅ Featured panel toggle (excellence|duty)
    s.setdefault("featured_panel", getattr(settings_obj, "featured_panel", "excellence") or "excellence")

    s.setdefault("refresh_interval_sec", getattr(settings_obj, "refresh_interval_sec", 10) or 10)
    s.setdefault("standby_scroll_speed", getattr(settings_obj, "standby_scroll_speed", 0.8) or 0.8)
    s.setdefault("periods_scroll_speed", getattr(settings_obj, "periods_scroll_speed", 0.5) or 0.5)

    # ✅ لون شاشة العرض (اختياري)
    accent = getattr(settings_obj, "display_accent_color", None) or s.get("display_accent_color")
    if isinstance(accent, str):
        accent = accent.strip()
    else:
        accent = None
    if accent and not re.match(r"^#[0-9A-Fa-f]{6}$", accent):
        accent = None
    s["display_accent_color"] = accent
    snap["settings"] = s

    # ✅ ROOT FIX: merge real data
    if merge_real_data:
        # ✅ ROOT FIX: merge real data
        _merge_real_data_into_snapshot(request, snap, settings_obj)

    # ✅ لو period_classes فاضية — نعبيها من ClassLesson
    if merge_real_data:
        # ✅ لو period_classes فاضية — نعبيها من ClassLesson
        try:
            current = snap.get("current_period") or {}
            kind = None
            if isinstance(current, dict):
                kind = current.get("kind") or current.get("type")
            if not kind:
                kind = (snap.get("state") or {}).get("type")

            if kind == "period" and not snap.get("period_classes"):
                meta = snap.get("meta") or {}
                weekday_raw = meta.get("weekday")
                try:
                    weekday = int(weekday_raw) if weekday_raw not in (None, "") else ((timezone.localdate().weekday() + 1) % 7)
                except Exception:
                    weekday = (timezone.localdate().weekday() + 1) % 7
                period_index = _infer_period_index(settings_obj, weekday, current if isinstance(current, dict) else None)
                if period_index:
                    snap["period_classes"] = _build_period_classes(settings_obj, weekday, period_index)
                    if isinstance(snap.get("current_period"), dict) and _is_missing_index(snap["current_period"]):
                        snap["current_period"]["index"] = period_index
        except Exception:
            logger.exception("snapshot: failed to fill period_classes")

        # ✅ ضمان ظهور رقم الحصة للـ current و next
        try:
            meta = snap.get("meta") or {}
            weekday_raw = meta.get("weekday")
            try:
                weekday = int(weekday_raw) if weekday_raw not in (None, "") else ((timezone.localdate().weekday() + 1) % 7)
            except Exception:
                weekday = (timezone.localdate().weekday() + 1) % 7

            curp = snap.get("current_period")
            if isinstance(curp, dict) and _is_missing_index(curp):
                idx = _infer_period_index(settings_obj, weekday, curp)
                if idx:
                    curp["index"] = idx

            nxtp = snap.get("next_period")
            if isinstance(nxtp, dict) and _is_missing_index(nxtp):
                idx2 = _infer_period_index(settings_obj, weekday, nxtp)
                if idx2:
                    nxtp["index"] = idx2
        except Exception:
            logger.exception("snapshot: failed to ensure current/next period index")

    return snap


@require_GET
def snapshot(request, token: str | None = None):
    """
    GET /api/display/snapshot/
    GET /api/display/snapshot/<token>/
    """
    try:
        # IMPORTANT (Production): do not allow query params to defeat caching.
        # Some screens may accidentally run with `?debug=1` / `?nocache=1` and spam the server.
        # We only honor nocache while developing locally (DEBUG=True).
        force_nocache = bool(dj_settings.DEBUG) and (request.GET.get("nocache") or "").strip().lower() in {"1", "true", "yes"}

        path = getattr(request, "path", "") or ""
        is_snapshot_path = path.startswith("/api/display/snapshot/")

        app_rev = _app_revision()

        def _finalize(resp, *, cache_status: str, device_bound: bool | None = None):
            if not resp.get("Cache-Control"):
                resp["Cache-Control"] = "no-store"
            # Keep compression negotiation; never vary on Cookie.
            resp["Vary"] = "Accept-Encoding"
            resp["X-Snapshot-Cache"] = cache_status
            if device_bound is not None:
                resp["X-Snapshot-Device-Bound"] = "1" if device_bound else "0"
            if app_rev:
                resp["X-App-Revision"] = app_rev
            return resp

        token_value = _extract_token(request, token)
        if not token_value:
            resp = JsonResponse(
                _fallback_payload("رمز الدخول غير صحيح"),
                json_dumps_params={"ensure_ascii": False},
                status=403,
            )
            return _finalize(resp, cache_status="ERROR", device_bound=False if is_snapshot_path else None)

        token_hash = _sha256(token_value)

        # === ANTI-LOOP GUARD (ISSUE #4) ===
        # If a token is looping (>30 req/min), force a long sleep without erroring.
        if not _snapshot_anti_loop_check(token_hash):
            if dj_settings.DEBUG:
                logger.warning("Anti-loop triggered for token_hash=%s", token_hash[:8])
            
            # Return valid (but empty/safe) payload with long refresh
            payload = _fallback_payload("التحديث متوقف مؤقتًا (حماية النظام)")
            payload["settings"]["refresh_interval_sec"] = 3600
            
            resp = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
            return _finalize(resp, cache_status="LOOP", device_bound=True if is_snapshot_path else None)
        # ==================================

        device_key = ""
        if is_snapshot_path:
            # Device binding without cookies: bind token -> device_key (header or query)
            device_key = (request.headers.get("X-Display-Device") or "").strip()
            if not device_key:
                device_key = (request.GET.get("dk") or request.GET.get("device_key") or "").strip()

            if not device_key:
                resp = JsonResponse({"detail": "device_required"}, status=403)
                return _finalize(resp, cache_status="ERROR", device_bound=False)

            device_hash = _sha256(device_key)

            # Rate limit: 1 req/sec per token+device with burst 3
            if not _snapshot_rate_limit_allow(token_hash, device_hash):
                resp = JsonResponse({"detail": "rate_limited"}, status=429)
                return _finalize(resp, cache_status="MISS", device_bound=True)

            bind_key = f"bind:snapshot:{token_hash}"

            # Prefer DB binding if this token belongs to a DisplayScreen.
            # This keeps "unbind" actions in the dashboard effective.
            screen = None
            try:
                screen = DisplayScreen.objects.only("id", "bound_device_id", "bound_at").filter(token=token_value).first()
            except Exception:
                screen = None

            db_bound = (getattr(screen, "bound_device_id", "") or "").strip() if screen else ""
            if db_bound:
                if db_bound != device_key:
                    resp = JsonResponse(
                        {
                            "detail": "screen_bound",
                            "message": "هذه الشاشة مرتبطة بجهاز آخر",
                        },
                        status=403,
                    )
                    return _finalize(resp, cache_status="ERROR", device_bound=True)

                # Keep cache binding in sync
                try:
                    cache.set(bind_key, device_key, timeout=_snapshot_bind_ttl_seconds())
                except Exception:
                    pass
            else:
                # If DB says unbound, delete any stale cache binding and bind to this device.
                existing = cache.get(bind_key)
                if existing and str(existing) != device_key:
                    try:
                        cache.delete(bind_key)
                    except Exception:
                        pass

                try:
                    cache.set(bind_key, device_key, timeout=_snapshot_bind_ttl_seconds())
                except Exception:
                    pass

                # Persist binding in DB when possible (so dashboard can unbind it).
                if screen:
                    try:
                        screen.bound_device_id = device_key
                        screen.bound_at = timezone.now()
                        screen.save(update_fields=["bound_device_id", "bound_at"])
                    except Exception:
                        pass

        # Phase 2: token cache (tenant-safe when school_id known)
        cache_key = get_cache_key(token_hash)

        cached_entry = None if force_nocache else cache.get(cache_key)
        if isinstance(cached_entry, dict) and isinstance(cached_entry.get("snap"), dict) and isinstance(cached_entry.get("etag"), str):
            _metrics_incr("metrics:snapshot_cache:token_hit")
            _metrics_log_maybe()
            inm = _parse_if_none_match(request.headers.get("If-None-Match"))
            if inm and inm == cached_entry.get("etag"):
                resp = HttpResponseNotModified()
                resp["ETag"] = f"\"{cached_entry['etag']}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)
            resp = JsonResponse(cached_entry["snap"], json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{cached_entry['etag']}\""
            return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

        _metrics_incr("metrics:snapshot_cache:token_miss")
        _metrics_log_maybe()

        settings_obj = None
        hashed_token = token_hash
        cached_school_id = None

        # 0) ✅ Cache Hit: Check if token is already mapped to school_id
        if token_value and len(token_value) > 10:
            # Negative cache check
            neg_key = f"display:token_neg:{hashed_token}"
            if cache.get(neg_key):
                resp = JsonResponse(
                    _fallback_payload("رمز الدخول غير صحيح (cached)"),
                    json_dumps_params={"ensure_ascii": False},
                    status=403,
                )
                resp["Cache-Control"] = "no-store"
                return _finalize(resp, cache_status="ERROR", device_bound=True if is_snapshot_path else None)

            # Positive cache check
            map_key = f"display:token_map:{hashed_token}"
            cached_map = cache.get(map_key)
            if cached_map:
                if isinstance(cached_map, dict):
                    cached_school_id = cached_map.get("school_id")
                else:
                    # Legacy or simple integer fallback
                    try:
                        cached_school_id = int(cached_map)
                    except:
                        pass
        
        # 1) If we have school_id, try to fetch Snapshot directly from cache
        if cached_school_id and not force_nocache:
            # Bump cache version v1 -> v2 to invalidate old stuck "Off" states
            snap_key = f"snapshot:v2:school:{cached_school_id}"
            cached_snap = cache.get(snap_key)
            if isinstance(cached_snap, dict):
                _metrics_incr("metrics:snapshot_cache:school_hit")
                _metrics_log_maybe()
                # We'll still go through token-keyed cache so ETag/304 and rate limit are consistent.
                try:
                    json_bytes = _stable_json_bytes(cached_snap)
                    etag = _etag_from_json_bytes(json_bytes)
                    token_timeout = _active_window_cache_ttl_seconds() if _is_active_window(cached_snap) else _steady_snapshot_cache_ttl_seconds(cached_snap)
                    tok_key = get_cache_key(token_hash, int(cached_school_id))
                    cache.set(tok_key, {"snap": cached_snap, "etag": etag}, timeout=token_timeout)
                except Exception:
                    etag = None

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if etag and inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                resp = JsonResponse(cached_snap, json_dumps_params={"ensure_ascii": False})
                if etag:
                    resp["ETag"] = f"\"{etag}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

            # steady snapshot fallback (long TTL outside window/holidays)
            # Bump cache version v2 -> v3
            steady_key = f"snapshot:v3:school:{int(cached_school_id)}:steady:{str(timezone.localdate())}"
            cached_steady = cache.get(steady_key)
            if isinstance(cached_steady, dict):
                _metrics_incr("metrics:snapshot_cache:steady_hit")
                _metrics_log_maybe()
                try:
                    json_bytes = _stable_json_bytes(cached_steady)
                    etag = _etag_from_json_bytes(json_bytes)
                    token_timeout = _steady_snapshot_cache_ttl_seconds(cached_steady)
                    tok_key = get_cache_key(token_hash, int(cached_school_id))
                    cache.set(tok_key, {"snap": cached_steady, "etag": etag}, timeout=token_timeout)
                except Exception:
                    etag = None

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if etag and inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                resp = JsonResponse(cached_steady, json_dumps_params={"ensure_ascii": False})
                if etag:
                    resp["ETag"] = f"\"{etag}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

            _metrics_incr("metrics:snapshot_cache:school_miss")
            _metrics_incr("metrics:snapshot_cache:steady_miss")
            _metrics_log_maybe()

            # If snapshot missing, we need settings_obj to build it
            try:
                settings_obj = _get_settings_by_school_id(int(cached_school_id))
            except Exception:
                pass

        # 2) DisplayScreen (DB Lookup if not found yet)
        if not settings_obj:
            settings_obj = _match_settings_via_display_screen(token_value) if token_value else None

        # 3) fallback token search
        if not settings_obj and token_value:
            settings_obj = _get_settings_by_token(token_value)

        # 4) school_id param
        if not settings_obj:
            school_id_raw = (request.GET.get("school_id") or request.GET.get("school") or "").strip()
            if school_id_raw.isdigit():
                settings_obj = _get_settings_by_school_id(int(school_id_raw))

        # 5) single settings fallback
        if not settings_obj:
            # ✅ Negative Cache: Cache invalid token to prevent DB hammering
            if token_value and len(token_value) > 10:
                neg_key = f"display:token_neg:{hashed_token}"
                cache.set(neg_key, "1", timeout=60) # 60 seconds

            total = SchoolSettings.objects.count()
            if total == 1:
                settings_obj = SchoolSettings.objects.select_related("school").first()
            else:
                if dj_settings.DEBUG:
                    logger.warning(
                        "snapshot: no match. token=%s school_id=%s total_settings=%s",
                        (token_value[:10] + "...") if token_value else None,
                        request.GET.get("school_id") or request.GET.get("school"),
                        total,
                    )
                resp = JsonResponse(_fallback_payload("إعدادات المدرسة غير مهيأة"), json_dumps_params={"ensure_ascii": False})
                resp["Cache-Control"] = "no-store"
                return _finalize(resp, cache_status="ERROR", device_bound=True if is_snapshot_path else None)
        
        # ✅ Cache Update: Store valid token mapping if not cached (24h)
        if token_value and settings_obj and len(token_value) > 10 and not cached_school_id:
            map_key = f"display:token_map:{hashed_token}"
            try:
                if getattr(settings_obj, 'school_id', None):
                   # Store dict compatible with middleware
                   payload = {"school_id": settings_obj.school_id}
                   # We don't have screen ID here easily unless we fetched via _match_settings_via_display_screen
                   # But middleware will update it with full details on next hit.
                   cache.set(map_key, payload, timeout=86400) # 24 hours
            except Exception:
                pass

        # 6) Phase 2: build snapshot once per school (stampede guard)
        school_id = int(getattr(settings_obj, "school_id", None) or 0)
        tenant_cache_key = get_cache_key(token_hash, school_id)
        if tenant_cache_key != cache_key:
            cached_entry2 = None if force_nocache else cache.get(tenant_cache_key)
            if isinstance(cached_entry2, dict) and isinstance(cached_entry2.get("snap"), dict) and isinstance(cached_entry2.get("etag"), str):
                _metrics_incr("metrics:snapshot_cache:token_hit")
                _metrics_log_maybe()
                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == cached_entry2.get("etag"):
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{cached_entry2['etag']}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)
                resp = JsonResponse(cached_entry2["snap"], json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{cached_entry2['etag']}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

        snap_key = _snapshot_cache_key(settings_obj)
        steady_key = f"snapshot:v2:school:{school_id}:steady:{str(timezone.localdate())}"

        if not force_nocache:
            cached_school = cache.get(snap_key)
            if isinstance(cached_school, dict):
                _metrics_incr("metrics:snapshot_cache:school_hit")
                _metrics_log_maybe()
                json_bytes = _stable_json_bytes(cached_school)
                etag = _etag_from_json_bytes(json_bytes)
                token_timeout = _active_window_cache_ttl_seconds() if _is_active_window(cached_school) else _steady_snapshot_cache_ttl_seconds(cached_school)
                try:
                    cache.set(tenant_cache_key, {"snap": cached_school, "etag": etag}, timeout=token_timeout)
                except Exception:
                    pass

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)
                resp = JsonResponse(cached_school, json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{etag}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

            cached_steady2 = cache.get(steady_key)
            if isinstance(cached_steady2, dict):
                _metrics_incr("metrics:snapshot_cache:steady_hit")
                _metrics_log_maybe()
                json_bytes = _stable_json_bytes(cached_steady2)
                etag = _etag_from_json_bytes(json_bytes)
                token_timeout = _steady_snapshot_cache_ttl_seconds(cached_steady2)
                try:
                    cache.set(tenant_cache_key, {"snap": cached_steady2, "etag": etag}, timeout=token_timeout)
                except Exception:
                    pass

                inm = _parse_if_none_match(request.headers.get("If-None-Match"))
                if inm and inm == etag:
                    resp = HttpResponseNotModified()
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)
                resp = JsonResponse(cached_steady2, json_dumps_params={"ensure_ascii": False})
                resp["ETag"] = f"\"{etag}\""
                return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

        # Stampede lock: one build per school
        school_lock_key = f"lock:{snap_key}"
        have_lock = True
        if not force_nocache:
            try:
                have_lock = bool(cache.add(school_lock_key, "1", timeout=_snapshot_build_lock_ttl_seconds()))
            except Exception:
                have_lock = True

        if not have_lock:
            # Another worker is building this school's snapshot.
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                cached_school = cache.get(snap_key)
                if isinstance(cached_school, dict):
                    json_bytes = _stable_json_bytes(cached_school)
                    etag = _etag_from_json_bytes(json_bytes)
                    try:
                        cache.set(tenant_cache_key, {"snap": cached_school, "etag": etag}, timeout=_active_window_cache_ttl_seconds())
                    except Exception:
                        pass
                    resp = JsonResponse(cached_school, json_dumps_params={"ensure_ascii": False})
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                cached_steady2 = cache.get(steady_key)
                if isinstance(cached_steady2, dict):
                    json_bytes = _stable_json_bytes(cached_steady2)
                    etag = _etag_from_json_bytes(json_bytes)
                    try:
                        cache.set(tenant_cache_key, {"snap": cached_steady2, "etag": etag}, timeout=_steady_snapshot_cache_ttl_seconds(cached_steady2))
                    except Exception:
                        pass
                    resp = JsonResponse(cached_steady2, json_dumps_params={"ensure_ascii": False})
                    resp["ETag"] = f"\"{etag}\""
                    return _finalize(resp, cache_status="HIT", device_bound=True if is_snapshot_path else None)

                time.sleep(0.05)

            # No stale available: return a short-lived steady snapshot to avoid stampede.
            tmp = build_steady_snapshot(
                request,
                settings_obj,
                steady_state="BUILDING",
                refresh_interval_sec=10,
                label="جاري تجهيز الجدول...",
            )
            json_bytes = _stable_json_bytes(tmp)
            etag = _etag_from_json_bytes(json_bytes)
            try:
                cache.set(tenant_cache_key, {"snap": tmp, "etag": etag}, timeout=5)
            except Exception:
                pass
            resp = JsonResponse(tmp, json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{etag}\""
            return _finalize(resp, cache_status="STALE", device_bound=True if is_snapshot_path else None)

        try:
            t0 = time.monotonic()

            day_snap = _normalize_snapshot_keys(_call_build_day_snapshot(settings_obj))
            active_window = _is_active_window(day_snap)
            token_timeout = compute_dynamic_ttl_seconds(day_snap)

            if active_window:
                snap = _build_final_snapshot(request, settings_obj, day_snap=day_snap, merge_real_data=True)
                if not force_nocache:
                    try:
                        # Version v2
                        cache.set(f"snapshot:v2:school:{settings_obj.school_id}", snap, timeout=_active_window_cache_ttl_seconds())
                    except Exception:
                        pass
            else:
                snap = _build_final_snapshot(request, settings_obj, day_snap=day_snap, merge_real_data=False)

                meta = day_snap.get("meta") or {}
                is_school_day = bool(meta.get("is_school_day"))
                st = (day_snap.get("state") or {}) if isinstance(day_snap, dict) else {}
                st_type = str(st.get("type") or "").strip().lower()

                # Outside active window we want to dramatically reduce polling.
                # We still keep a periodic check so screens can resume automatically.
                base_refresh = int((day_snap.get("settings") or {}).get("refresh_interval_sec") or 3600)
                if not is_school_day:
                    # Holidays / no schedule: hourly check is enough.
                    refresh = max(base_refresh, 3600)
                elif st_type == "before":
                    # Before school: check occasionally; countdown/UI runs client-side.
                    refresh = max(base_refresh, 60)
                else:
                    # After school / off-hours: slow down to reduce load.
                    refresh = max(base_refresh, 600)

                # Safety clamp (5s .. 24h)
                refresh = max(5, min(86400, int(refresh)))

                if not is_school_day:
                    snap["state"]["type"] = "NO_SCHEDULE_TODAY"
                    snap["state"]["label"] = "لا يوجد جدول اليوم"
                elif st_type == "before":
                    snap["state"]["type"] = "BEFORE_SCHOOL"
                    snap["state"]["label"] = "قبل بداية الدوام"
                else:
                    snap["state"]["type"] = "OFF_HOURS"
                    snap["state"]["label"] = "انتهى الدوام"

                try:
                    snap["settings"]["refresh_interval_sec"] = int(refresh)
                except Exception:
                    pass

                # Align token cache TTL to the chosen off-hours refresh interval.
                try:
                    token_timeout = _steady_snapshot_cache_ttl_seconds(snap)
                except Exception:
                    pass

                if not force_nocache:
                    try:
                        cache.set(_steady_snapshot_cache_key(settings_obj, day_snap), snap, timeout=_steady_snapshot_cache_ttl_seconds(snap))
                    except Exception:
                        pass

            build_ms = int((time.monotonic() - t0) * 1000)
            _metrics_incr("metrics:snapshot_cache:build_count")
            _metrics_add("metrics:snapshot_cache:build_sum_ms", build_ms)
            _metrics_set_max("metrics:snapshot_cache:build_max_ms", build_ms)
            _metrics_log_maybe()

            json_bytes = _stable_json_bytes(snap)
            etag = _etag_from_json_bytes(json_bytes)

            if not force_nocache:
                try:
                    cache.set(tenant_cache_key, {"snap": snap, "etag": etag}, timeout=token_timeout)
                except Exception:
                    pass

            inm = _parse_if_none_match(request.headers.get("If-None-Match"))
            if inm and inm == etag:
                resp = HttpResponseNotModified()
                resp["ETag"] = f"\"{etag}\""
                return _finalize(resp, cache_status="MISS" if force_nocache else "MISS", device_bound=True if is_snapshot_path else None)

            resp = JsonResponse(snap, json_dumps_params={"ensure_ascii": False})
            resp["ETag"] = f"\"{etag}\""
            return _finalize(resp, cache_status="BYPASS" if force_nocache else "MISS", device_bound=True if is_snapshot_path else None)
        finally:
            if not force_nocache:
                try:
                    cache.delete(school_lock_key)
                except Exception:
                    pass

    except Exception as e:
        logger.exception("snapshot error: %s", e)
        resp = JsonResponse(_fallback_payload("حدث خطأ أثناء جلب البيانات"), json_dumps_params={"ensure_ascii": False})
        resp["Cache-Control"] = "no-store"
        resp["Vary"] = "Accept-Encoding"
        resp["X-Snapshot-Cache"] = "ERROR"
        if app_rev:
            resp["X-App-Revision"] = app_rev
        return resp
