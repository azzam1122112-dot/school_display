from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, time
from typing import Optional, Literal, List, Tuple

from django.utils import timezone

from .models import (
    SchoolSettings,
    DaySchedule,
    Period,
    Break,
    ClassLesson,
)
from standby.models import StandbyAssignment

StateType = Literal["before", "period", "break", "after", "off"]


@dataclass
class State:
    type: StateType
    current: Optional[dict] = None
    next: Optional[dict] = None
    countdown_seconds: Optional[int] = None


def _time_to_dt(day_zero: datetime, t: time) -> datetime:
    return day_zero.replace(
        hour=t.hour,
        minute=t.minute,
        second=t.second,
        microsecond=0,
    )


def _break_end(day_zero: datetime, b: Break) -> datetime:
    return _time_to_dt(day_zero, b.starts_at) + timedelta(
        minutes=int(b.duration_min)
    )


def _weekday_sunday_based(py_weekday: int) -> int:
    return (py_weekday + 1) % 7


def _weekday_db_monday_based(py_weekday: int) -> int:
    """Python: Monday=0..Sunday=6 -> DB: Monday=1..Sunday=7."""
    return py_weekday + 1


def compute_today_state(settings_obj: SchoolSettings) -> dict:
    now = timezone.localtime()
    today_zero = now.replace(hour=0, minute=0, second=0, microsecond=0)

    weekday_db = _weekday_db_monday_based(now.weekday())
    weekday_legacy = _weekday_sunday_based(now.weekday())
    try:
        day = (
            DaySchedule.objects.select_related("settings")
            .prefetch_related("periods", "breaks")
            .get(settings=settings_obj, weekday=weekday_db)
        )
    except DaySchedule.DoesNotExist:
        # Backward compatibility for older data (Sunday=0..Saturday=6)
        try:
            day = (
                DaySchedule.objects.select_related("settings")
                .prefetch_related("periods", "breaks")
                .get(settings=settings_obj, weekday=weekday_legacy)
            )
        except DaySchedule.DoesNotExist:
            return {"state": State(type="before").__dict__, "day": None}

    if not day.is_active:
        return {"state": State(type="off").__dict__, "day": None}

    periods: List[Period] = list(
        day.periods.order_by("index", "starts_at")
    )
    breaks: List[Break] = list(day.breaks.order_by("starts_at"))

    first_events: List[datetime] = []
    last_events: List[datetime] = []

    if periods:
        first_events.append(_time_to_dt(today_zero, periods[0].starts_at))
        last_events.append(_time_to_dt(today_zero, periods[-1].ends_at))

    if breaks:
        first_events.append(_time_to_dt(today_zero, breaks[0].starts_at))
        last_events.append(
            max(_break_end(today_zero, b) for b in breaks)
        )

    first_start = min(first_events) if first_events else None
    last_end = max(last_events) if last_events else None

    events: List[Tuple[str, datetime, datetime, object]] = []
    for p in periods:
        s = _time_to_dt(today_zero, p.starts_at)
        e = _time_to_dt(today_zero, p.ends_at)
        events.append(("period", s, e, p))
    for b in breaks:
        s = _time_to_dt(today_zero, b.starts_at)
        e = _break_end(today_zero, b)
        events.append(("break", s, e, b))

    events.sort(key=lambda x: x[1])

    if not events or (first_start and now < first_start):
        nxt = None
        if events:
            typ, s, e, obj = events[0]
            if typ == "period":
                nxt = {
                    "type": "period",
                    "index": obj.index,
                    "starts_at": obj.starts_at,
                    "ends_at": obj.ends_at,
                }
            else:
                nxt = {
                    "type": "break",
                    "label": obj.label,
                    "starts_at": obj.starts_at,
                    "ends_at": e.time(),
                }

        countdown = (
            int((first_start - now).total_seconds())
            if first_start
            else None
        )
        if countdown is not None:
            countdown = max(countdown, 0)

        state = State(
            type="before",
            current=None,
            next=nxt,
            countdown_seconds=countdown,
        )

    elif last_end and now >= last_end:
        state = State(
            type="after",
            current=None,
            next=None,
            countdown_seconds=None,
        )

    else:
        current_event: Optional[
            Tuple[str, datetime, datetime, object]
        ] = None
        for typ, s, e, obj in events:
            if s <= now < e:
                current_event = (typ, s, e, obj)
                break

        if current_event:
            typ, s, e, obj = current_event
            upcoming = [
                (t2, s2, e2, o2)
                for (t2, s2, e2, o2) in events
                if s2 >= e
            ]
            nxt = None
            if upcoming:
                t2, s2, e2, o2 = upcoming[0]
                if t2 == "period":
                    nxt = {
                        "type": "period",
                        "index": o2.index,
                        "starts_at": o2.starts_at,
                        "ends_at": o2.ends_at,
                    }
                else:
                    nxt = {
                        "type": "break",
                        "label": o2.label,
                        "starts_at": o2.starts_at,
                        "ends_at": e2.time(),
                    }

            countdown = int((e - now).total_seconds())
            countdown = max(countdown, 0)

            if typ == "period":
                cur = {
                    "index": obj.index,
                    "starts_at": obj.starts_at,
                    "ends_at": obj.ends_at,
                }
                state = State(
                    type="period",
                    current=cur,
                    next=nxt,
                    countdown_seconds=countdown,
                )
            else:
                cur = {
                    "label": obj.label,
                    "starts_at": obj.starts_at,
                    "ends_at": e.time(),
                }
                state = State(
                    type="break",
                    current=cur,
                    next=nxt,
                    countdown_seconds=countdown,
                )

        else:
            following = [
                (t, s, e, o)
                for (t, s, e, o) in events
                if s > now
            ]
            nxt = None
            if following:
                t2, s2, e2, o2 = following[0]
                if t2 == "period":
                    nxt = {
                        "type": "period",
                        "index": o2.index,
                        "starts_at": o2.starts_at,
                        "ends_at": o2.ends_at,
                    }
                else:
                    nxt = {
                        "type": "break",
                        "label": o2.label,
                        "starts_at": o2.starts_at,
                        "ends_at": e2.time(),
                    }
                countdown = int((s2 - now).total_seconds())
                countdown = max(countdown, 0)
            else:
                countdown = None

            state = State(
                type="before",
                current=None,
                next=nxt,
                countdown_seconds=countdown,
            )

    day_data = {
        "weekday": day.weekday,
        "weekday_display": day.get_weekday_display(),
        "periods_count": day.periods_count,
        "periods": [
            {
                "index": p.index,
                "starts_at": p.starts_at,
                "ends_at": p.ends_at,
            }
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


def get_current_lessons(settings: SchoolSettings) -> dict:
    now = timezone.localtime()

    weekday_db = _weekday_db_monday_based(now.weekday())
    weekday_legacy = _weekday_sunday_based(now.weekday())

    try:
        day = DaySchedule.objects.get(
            settings=settings,
            weekday=weekday_db,
            is_active=True,
        )
    except DaySchedule.DoesNotExist:
        # Backward compatibility for older data (Sunday=0..Saturday=6)
        try:
            day = DaySchedule.objects.get(
                settings=settings,
                weekday=weekday_legacy,
                is_active=True,
            )
            weekday_db = weekday_legacy
        except DaySchedule.DoesNotExist:
            return {
                "period": None,
                "lessons": [],
            }

    weekday = weekday_db

    # continue with resolved weekday
    if not day:
        return {
            "period": None,
            "lessons": [],
        }

    current_period = (
        Period.objects.filter(
            day=day,
            starts_at__lte=now.time(),
            ends_at__gt=now.time(),
        )
        .order_by("index")
        .first()
    )

    if not current_period:
        return {
            "period": None,
            "lessons": [],
        }

    standby_map = {}
    for sb in StandbyAssignment.objects.filter(
        school=settings.school if hasattr(settings, 'school') else None,
        date=timezone.localdate(),
        period_index=current_period.index,
    ):
        standby_map[sb.class_name] = sb

    lessons = []
    qs = ClassLesson.objects.filter(
        settings=settings,
        weekday=weekday,
        period_index=current_period.index,
    ).select_related("school_class", "subject", "teacher")

    for cls in qs:
        standby = standby_map.get(cls.school_class_id)
        if standby:
            lessons.append(
                {
                    "class_name": cls.school_class.name,
                    "subject": "انتظار",
                    "teacher": getattr(
                        standby.assigned_teacher, "name", ""
                    ),
                    "type": "standby",
                }
            )
        else:
            lessons.append(
                {
                    "class_name": cls.school_class.name,
                    "subject": cls.subject.name if cls.subject else "",
                    "teacher": cls.teacher.name if cls.teacher else "",
                    "type": "normal",
                }
            )

    return {
        "period": {
            "index": current_period.index,
            "start": str(current_period.starts_at),
            "end": str(current_period.ends_at),
        },
        "lessons": lessons,
    }
