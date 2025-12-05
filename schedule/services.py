# schedule/services.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional, Literal, List, Tuple

from django.utils import timezone

from .models import SchoolSettings, DaySchedule, Period, Break

StateType = Literal["before", "period", "break", "after", "off"]


@dataclass
class State:
    type: StateType
    current: Optional[dict] = None
    next: Optional[dict] = None
    countdown_seconds: Optional[int] = None  # المتبقي لنهاية الحالة الحالية أو بدء التالية (في حالة before)


def _time_to_dt(day_zero: datetime, t: time) -> datetime:
    """ضبط وقت على تاريخ اليوم (بلا تغيّر للمنطقة الزمنية)."""
    return day_zero.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)


def _break_end(day_zero: datetime, b: Break) -> datetime:
    """نهاية الفسحة = بدايتها + الدقائق."""
    return _time_to_dt(day_zero, b.starts_at) + timedelta(minutes=b.duration_min)


def _weekday_sunday_based(py_weekday: int) -> int:
    """
    تحويل Monday=0..Sunday=6 (بايثون) إلى Sunday=0..Saturday=6 (نماذجنا).
    Sunday-based = (python_weekday + 1) % 7
    """
    return (py_weekday + 1) % 7


def _first(lst):
    return lst[0] if lst else None


def compute_today_state(settings_obj: SchoolSettings) -> dict:
    """
    يحسب حالة اليوم:
      - before: قبل أول حدث قادم (أول حصة/فسحة)
      - period: داخل حصة
      - break : داخل فسحة
      - after : بعد انتهاء اليوم (لا أحداث قادمة)
    ويعيد:
      - current: معلومات الحدث الحالي (إن وُجد)
      - next   : الحدث التالي (إن وُجد)
      - countdown_seconds: المتبقي لانتهاء الحدث الحالي، أو لبدء الحدث التالي إن كنا في before
    """
    # الآن بتاريخ ووقت الخادم مضبوطًا على TIME_ZONE في الإعدادات
    now = timezone.localtime()
    today_zero = now.replace(hour=0, minute=0, second=0, microsecond=0)

    weekday_sunday0 = _weekday_sunday_based(now.weekday())
    try:
        # نجلب اليوم مع الحصص/الفسح مُرتّبة
        day = (
            DaySchedule.objects.select_related("settings")
            .prefetch_related("periods", "breaks")
            .get(settings=settings_obj, weekday=weekday_sunday0)
        )
    except DaySchedule.DoesNotExist:
        # لا يوجد ضبط لليوم — نرجع before بدون أحداث
        return {"state": State(type="before").__dict__, "day": None}

    if not day.is_active:
        # اليوم معطل (إجازة)
        return {"state": State(type="off").__dict__, "day": None}

    periods: List[Period] = list(day.periods.order_by("index", "starts_at"))
    breaks: List[Break] = list(day.breaks.order_by("starts_at"))

    # حساب حدود اليوم (من أول بداية لأي حدث إلى آخر نهاية لأي حدث)
    first_events: List[datetime] = []
    last_events: List[datetime] = []

    if periods:
        first_events.append(_time_to_dt(today_zero, periods[0].starts_at))
        last_events.append(_time_to_dt(today_zero, periods[-1].ends_at))

    if breaks:
        first_events.append(_time_to_dt(today_zero, breaks[0].starts_at))
        last_events.append(max(_break_end(today_zero, b) for b in breaks))

    first_start = min(first_events) if first_events else None
    last_end = max(last_events) if last_events else None

    # بناء قائمة الأحداث اليوم مرتّبة زمنيًا (نوع، بداية، نهاية، كائن)
    events: List[Tuple[str, datetime, datetime, object]] = []
    for p in periods:
        s = _time_to_dt(today_zero, p.starts_at)
        e = _time_to_dt(today_zero, p.ends_at)
        events.append(("period", s, e, p))
    for b in breaks:
        s = _time_to_dt(today_zero, b.starts_at)
        e = _break_end(today_zero, b)
        events.append(("break", s, e, b))
    events.sort(key=lambda x: x[1])  # حسب البداية

    # 1) قبل اليوم (قبل أول حدث)
    if not events or (first_start and now < first_start):
        nxt = None
        if events:
            typ, s, e, obj = events[0]
            if typ == "period":
                nxt = {"type": "period", "index": obj.index, "starts_at": obj.starts_at, "ends_at": obj.ends_at}
            else:
                nxt = {"type": "break", "label": obj.label, "starts_at": obj.starts_at, "ends_at": e.time()}
        countdown = int((first_start - now).total_seconds()) if first_start else None
        countdown = max(countdown, 0) if countdown is not None else None
        state = State(type="before", current=None, next=nxt, countdown_seconds=countdown)
    # 2) بعد اليوم (بعد آخر حدث)
    elif last_end and now >= last_end:
        state = State(type="after", current=None, next=None, countdown_seconds=None)
    else:
        # 3) داخل اليوم: نبحث هل نحن داخل حدث حاليًا؟
        current_event = None
        for typ, s, e, obj in events:
            if s <= now < e:
                current_event = (typ, s, e, obj)
                break

        if current_event:
            typ, s, e, obj = current_event
            # حدد الحدث التالي: أول حدث يبدأ بعد (الآن) — (لن توجد تداخلات بسبب تحقق الموديلات)
            upcoming = [(t2, s2, e2, o2) for (t2, s2, e2, o2) in events if s2 >= e]
            nxt = None
            if upcoming:
                t2, s2, e2, o2 = upcoming[0]
                if t2 == "period":
                    nxt = {"type": "period", "index": o2.index, "starts_at": o2.starts_at, "ends_at": o2.ends_at}
                else:
                    nxt = {"type": "break", "label": o2.label, "starts_at": o2.starts_at, "ends_at": e2.time()}

            countdown = int((e - now).total_seconds())
            countdown = max(countdown, 0)

            if typ == "period":
                cur = {"index": obj.index, "starts_at": obj.starts_at, "ends_at": obj.ends_at}
                state = State(type="period", current=cur, next=nxt, countdown_seconds=countdown)
            else:
                cur = {"label": obj.label, "starts_at": obj.starts_at, "ends_at": e.time()}
                state = State(type="break", current=cur, next=nxt, countdown_seconds=countdown)

        else:
            # 4) لسنا داخل حدث: نحن في فجوة بين حدثين داخل اليوم
            # اختر الحدث التالي الأقرب بعد الآن
            following = [(t, s, e, o) for (t, s, e, o) in events if s > now]
            nxt = None
            if following:
                t2, s2, e2, o2 = following[0]
                if t2 == "period":
                    nxt = {"type": "period", "index": o2.index, "starts_at": o2.starts_at, "ends_at": o2.ends_at}
                else:
                    nxt = {"type": "break", "label": o2.label, "starts_at": o2.starts_at, "ends_at": e2.time()}
                countdown = int((s2 - now).total_seconds())
                countdown = max(countdown, 0)
            else:
                countdown = None  # احتياطًا، لكن هذه الحالة تُغطّى بمنطق after بالأعلى عادةً

            # في الفجوات، نُرجع before مع عدّاد إلى بداية الحدث التالي
            state = State(type="before", current=None, next=nxt, countdown_seconds=countdown)

    # بيانات اليوم (للاستهلاك في الواجهة)
    day_data = {
        "weekday": day.weekday,
        "weekday_display": day.get_weekday_display(),
        "periods_count": day.periods_count,
        "periods": [
            {"index": p.index, "starts_at": p.starts_at, "ends_at": p.ends_at}
            for p in periods
        ],
        "breaks": [
            {
                "label": b.label,
                "starts_at": b.starts_at,
                "duration_min": b.duration_min,
                "ends_at": _break_end(today_zero, b).time(),
            }
            for b in breaks
        ],
    }

    return {
        "state": state.__dict__,
        "day": day_data,
    }
