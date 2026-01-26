# schedule/time_engine.py
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone


def _normalize_weekday_for_db(py_weekday: int) -> int:
    """
    Python: Monday=0 .. Sunday=6
    DB: Monday=1 .. Sunday=7
    """
    return py_weekday + 1


def _to_aware_dt(today, t, tz):
    dt = datetime.combine(today, t)
    return timezone.make_aware(dt, tz) if timezone.is_naive(dt) else dt


def _get_manager(obj, *names):
    for name in names:
        m = getattr(obj, name, None)
        if m is None:
            continue
        # RelatedManager has .all()
        if hasattr(m, "all"):
            return m
    return None


def build_day_snapshot(settings, now=None):
    """
    Snapshot contract for /api/display/snapshot

    returns:
      meta, settings, state, current_period, next_period, day_path,
      period_classes, standby{items}, excellence{items}
    """
    if now is None:
        now = timezone.localtime()

    # timezone
    tz_name = getattr(settings, "timezone_name", None) or "Asia/Riyadh"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Riyadh")

    now = timezone.localtime(now, tz)
    today = now.date()

    # ✅ FIX: map python weekday -> DB weekday
    weekday = _normalize_weekday_for_db(today.weekday())

    # theme mapping (لو عندك "default")
    raw_theme = (getattr(settings, "theme", None) or "indigo").strip().lower()
    if raw_theme in ("default", "dark", "light", ""):
        raw_theme = "indigo"

    # ✅ settings payload دائمًا كامل
    settings_payload = {
        "name": getattr(settings, "name", "") or "",
        "logo_url": getattr(settings, "logo_url", None),
        "theme": raw_theme,
        "timezone_name": tz_name,
        "refresh_interval_sec": int(getattr(settings, "refresh_interval_sec", 30) or 30),
        "standby_scroll_speed": float(getattr(settings, "standby_scroll_speed", 0.8) or 0.8),
        "periods_scroll_speed": float(getattr(settings, "periods_scroll_speed", 0.5) or 0.5),
    }

    # الحصول على جدول اليوم
    day_qs = getattr(settings, "day_schedules", None)
    day = None
    if day_qs is not None and hasattr(day_qs, "filter"):
        day = day_qs.filter(weekday=weekday, is_active=True).first()

    if not day:
        # Optimization: Strict stop on holidays (reduced to 15m to allow updates/wake-up)
        settings_payload["refresh_interval_sec"] = 900
        return {
            "now": now.isoformat(),
            "meta": {
                "date": str(today),
                "weekday": weekday,
                "is_school_day": False,
                "is_active_window": False,
                "active_window": None,
            },
            "settings": settings_payload,
            "state": {"type": "off", "label": "لا يوجد جدول لليوم", "from": None, "to": None, "remaining_seconds": None},
            "current_period": None,
            "next_period": None,
            "day_path": [],
            "period_classes": [],
            "standby": {"items": []},
            "excellence": {"items": []},
        }

    # periods/breaks managers (توافق مع related_name)
    periods_m = _get_manager(day, "periods", "period_set")
    breaks_m = _get_manager(day, "breaks", "break_set")

    timeline = []

    if periods_m:
        for p in periods_m.select_related("subject", "teacher", "school_class").all():
            # تجاهل أي صف بدون وقت صحيح
            if not getattr(p, "starts_at", None) or not getattr(p, "ends_at", None):
                continue

            start = _to_aware_dt(today, p.starts_at, tz)
            end = _to_aware_dt(today, p.ends_at, tz)
            if end <= start:
                continue

            timeline.append({
                "kind": "period",
                "index": getattr(p, "index", None),
                "label": (p.subject.name if getattr(p, "subject", None) else "حصة"),
                "class": (p.school_class.name if getattr(p, "school_class", None) else None),
                "teacher": (p.teacher.name if getattr(p, "teacher", None) else None),
                "start": start,
                "end": end,
            })

    if breaks_m:
        for b in breaks_m.all():
            if not getattr(b, "starts_at", None):
                continue
            start = _to_aware_dt(today, b.starts_at, tz)
            dur = int(getattr(b, "duration_min", 0) or 0)
            if dur <= 0:
                continue
            end = start + timedelta(minutes=dur)
            timeline.append({
                "kind": "break",
                "label": getattr(b, "label", None) or "استراحة",
                "start": start,
                "end": end,
            })

    if not timeline:
        # Optimization: Strict stop if empty timeline (reduced to 15m)
        settings_payload["refresh_interval_sec"] = 900
        return {
            "now": now.isoformat(),
            "meta": {
                "date": str(today),
                "weekday": weekday,
                "is_school_day": True,
                "is_active_window": False,
                "active_window": None,
            },
            "settings": settings_payload,
            "state": {"type": "off", "label": "لا يوجد مسار زمني لليوم", "from": None, "to": None, "remaining_seconds": None},
            "current_period": None,
            "next_period": None,
            "day_path": [],
            "period_classes": [],
            "standby": {"items": []},
            "excellence": {"items": []},
        }

    # === Optimization: Strict Active Window & Smart Wakeup ===
    start_t = min(t["start"] for t in timeline)
    end_t = max(t["end"] for t in timeline)

    # Active Window: Start - 30m to End + 30m
    active_start = start_t - timedelta(minutes=30)
    active_end = end_t + timedelta(minutes=30)
    
    # ✅ Strict Off-Hours Logic
    if now < active_start:
        # Before Window: Sleep / Smart Wakeup
        wait_seconds = (active_start - now).total_seconds()
        # Sleep until active_start, but poll every 15m max to catch schedule changes
        settings_payload["refresh_interval_sec"] = min(900, max(10, int(wait_seconds)))
        
        return {
            "now": now.isoformat(),
            "meta": {
                "date": str(today),
                "weekday": weekday,
                "is_school_day": True,
                "is_active_window": False,
                "active_window": {
                    "start": active_start.isoformat(),
                    "end": active_end.isoformat(),
                },
            },
            "settings": settings_payload,
            "state": {
                "type": "off", 
                "label": "خارج وقت الدوام", 
                "from": None, 
                "to": None, 
                "remaining_seconds": None
            },
            "current_period": None,
            "next_period": None,
            "day_path": [],
            "period_classes": [],
            "standby": {"items": []},
            "excellence": {"items": []},
        }

    elif now > active_end:
        # After Window: Sleep
        settings_payload["refresh_interval_sec"] = 900
        return {
            "now": now.isoformat(),
            "meta": {
                "date": str(today),
                "weekday": weekday,
                "is_school_day": True,
                "is_active_window": False,
                "active_window": {
                    "start": active_start.isoformat(),
                    "end": active_end.isoformat(),
                },
            },
            "settings": settings_payload,
            "state": {
                "type": "off", 
                "label": "انتهى الدوام", 
                "from": None, 
                "to": None, 
                "remaining_seconds": None
            },
            "current_period": None,
            "next_period": None,
            "day_path": [],
            "period_classes": [],
            "standby": {"items": []},
            "excellence": {"items": []},
        }

    # Within Active Window
    is_active_window = True
    active_window_meta = {

        "start": active_start.isoformat(),
        "end": active_end.isoformat(),
    }
    # ===================================

    timeline.sort(key=lambda x: x["start"])

    current = None
    next_item = None

    for i, block in enumerate(timeline):
        if block["start"] <= now < block["end"]:
            current = block
            next_item = timeline[i + 1] if i + 1 < len(timeline) else None
            break
        if now < block["start"]:
            next_item = block
            break

    def fmt(block):
        if not block:
            return None
        out = {
            "kind": block["kind"],
            "label": block.get("label"),
            "class": block.get("class"),
            "teacher": block.get("teacher"),
            "from": block["start"].strftime("%H:%M"),
            "to": block["end"].strftime("%H:%M"),
        }
        # ✅ important: keep period index so UI can show "حصة (رقم)" and
        # server-side merge can build period_classes without fragile time matching.
        if block.get("kind") == "period":
            out["index"] = block.get("index")
        return out

    day_path = [{
        "kind": b["kind"],
        "label": b.get("label"),
        "from": b["start"].strftime("%H:%M"),
        "to": b["end"].strftime("%H:%M"),
    } for b in timeline]

    # state
    if current:
        state = {
            "type": current["kind"],
            "label": current.get("label"),
            "from": current["start"].strftime("%H:%M"),
            "to": current["end"].strftime("%H:%M"),
            "remaining_seconds": max(0, int((current["end"] - now).total_seconds())),
        }
        if current.get("kind") == "period":
            state["period_index"] = current.get("index")
    elif next_item:
        first = timeline[0]
        if now < first["start"]:
            state = {
                "type": "before",
                "label": "قبل بداية اليوم الدراسي",
                "from": first["start"].strftime("%H:%M"),
                "to": first["end"].strftime("%H:%M"),
                "remaining_seconds": max(0, int((first["start"] - now).total_seconds())),
            }
        else:
            state = {"type": "day", "label": "اليوم الدراسي", "from": None, "to": None, "remaining_seconds": None}
    else:
        # ✅ استخدم آخر نهاية فعلية (max end)
        last = max(timeline, key=lambda x: x["end"])
        state = {
            "type": "after",
            "label": "انتهى اليوم الدراسي",
            "from": last["start"].strftime("%H:%M"),
            "to": last["end"].strftime("%H:%M"),
            "remaining_seconds": 0,
        }

    return {
        "now": now.isoformat(),
        "meta": {
            "date": str(today),
            "weekday": weekday,
            "is_school_day": True,
            "is_active_window": is_active_window,
            "active_window": active_window_meta,
        },
        "settings": settings_payload,
        "state": state,
        "current_period": (fmt(current) | ({"remaining_seconds": max(0, int((current["end"] - now).total_seconds()))} if current else {})) if current else None,
        "next_period": fmt(next_item),
        "day_path": day_path,
        "period_classes": [],
        "standby": {"items": []},
        "excellence": {"items": []},
    }
