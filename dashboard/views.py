from __future__ import annotations

from datetime import datetime, date, time, timedelta
import csv
import io
import math

from django.db import models, transaction
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Max
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .permissions import manager_required
from .forms import (
    SchoolSettingsForm,
    DayScheduleForm,
    PeriodFormSet,
    BreakFormSet,
    AnnouncementForm,
    ExcellenceForm,
    StandbyForm,
    DisplayScreenForm,
    LessonForm,
)
from schedule.models import (
    SchoolSettings,
    DaySchedule,
    ClassLesson,
    Subject,
    Teacher,
    SchoolClass,
    Period,
)
from notices.models import Announcement, Excellence
from standby.models import StandbyAssignment
from core.models import DisplayScreen


SCHOOL_WEEK = [
    (0, "الأحد"),
    (1, "الاثنين"),
    (2, "الثلاثاء"),
    (3, "الأربعاء"),
    (4, "الخميس"),
    (5, "الجمعة"),
    (6, "السبت"),
]
WEEKDAY_MAP = dict(SCHOOL_WEEK)


def _collect_form_errors(*objs) -> str:
    msgs: list[str] = []

    def _push(err):
        if not err:
            return
        if isinstance(err, (list, tuple)):
            for e in err:
                _push(e)
        else:
            msgs.append(str(err))

    for obj in objs:
        if hasattr(obj, "non_form_errors"):
            _push(obj.non_form_errors())

        if hasattr(obj, "forms"):
            for f in obj.forms:
                if hasattr(f, "errors"):
                    if isinstance(f.errors, dict):
                        for elist in f.errors.values():
                            _push(elist)
                    else:
                        _push(f.errors)

        if hasattr(obj, "errors"):
            errs = obj.errors
            if isinstance(errs, dict):
                for elist in errs.values():
                    _push(elist)
            elif isinstance(errs, (list, tuple)):
                for item in errs:
                    if isinstance(item, dict):
                        for elist in item.values():
                            _push(elist)
                    else:
                        _push(item)

    seen, ordered = set(), []
    for m in msgs:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return " | ".join(ordered)


def _rev_manager(obj, preferred: str, fallback: str):
    mgr = getattr(obj, preferred, None)
    if mgr is None:
        mgr = getattr(obj, fallback)
    return mgr


def _parse_hhmm_or_hhmmss(s: str) -> time:
    s = (s or "").strip()
    if not s:
        raise ValueError("الوقت مطلوب.")
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError("صيغة الوقت غير صحيحة. استخدم HH:MM أو HH:MM:SS")


def _to_int(val: str | None, default: int = 0, *, allow_negative: bool = False) -> int:
    try:
        x = int(val) if val not in (None, "") else default
    except (TypeError, ValueError):
        x = default
    if not allow_negative and x < 0:
        raise ValueError("القيم لا يجوز أن تكون سالبة.")
    return x


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:index")
    if request.method == "POST":
        u = (request.POST.get("username") or "").strip()
        p = request.POST.get("password") or ""
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect("dashboard:index")
        messages.error(request, "بيانات الدخول غير صحيحة.")
    return render(request, "dashboard/login.html")


def demo_login(request):
    try:
        user = User.objects.get(username="demo_user")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "مرحباً بك في النسخة التجريبية! يمكنك استكشاف النظام بحرية.")
        return redirect("dashboard:index")
    except User.DoesNotExist:
        messages.error(request, "الحساب التجريبي غير مفعل حالياً.")
        return redirect("dashboard:login")


def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


@manager_required
def change_password(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "تم تغيير كلمة المرور بنجاح!")
            return redirect("dashboard:index")
        messages.error(request, "الرجاء تصحيح الأخطاء أدناه.")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "dashboard/change_password.html", {"form": form})


@manager_required
def index(request):
    school = request.user.profile.school
    today = timezone.localdate()
    stats = {
        "ann_count": Announcement.objects.filter(school=school).count(),
        "exc_count": Excellence.objects.filter(school=school).count(),
        "standby_today": StandbyAssignment.objects.filter(school=school, date=today).count(),
    }
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    return render(
        request,
        "dashboard/index.html",
        {
            "stats": stats,
            "settings": settings_obj,
        },
    )


@manager_required
def school_settings(request):
    school = request.user.profile.school
    obj, created = SchoolSettings.objects.get_or_create(
        school=school,
        defaults={"name": school.name},
    )
    if request.method == "POST":
        form = SchoolSettingsForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ إعدادات المدرسة.")
            return redirect("dashboard:settings")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSettingsForm(instance=obj)
    return render(request, "dashboard/settings.html", {"form": form})


@manager_required
def days_list(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    existing = set(
        DaySchedule.objects.filter(settings=settings_obj, weekday__in=WEEKDAY_MAP.keys()).values_list(
            "weekday", flat=True
        )
    )
    for w in WEEKDAY_MAP.keys():
        if w not in existing:
            DaySchedule.objects.create(
                settings=settings_obj,
                weekday=w,
                periods_count=7 if w in (0, 1) else 6,
            )

    days = list(
        DaySchedule.objects.filter(settings=settings_obj, weekday__in=WEEKDAY_MAP.keys())
        .order_by("weekday")
        .prefetch_related("periods", "breaks")
    )

    total_periods = 0
    for d in days:
        d.day_name = WEEKDAY_MAP.get(d.weekday, str(d.weekday))
        d.breaks_count = d.breaks.count()
        periods = sorted(d.periods.all(), key=lambda p: p.starts_at)
        if periods:
            d.first_period_time = periods[0].starts_at.strftime("%H:%M")
            d.last_period_time = periods[-1].ends_at.strftime("%H:%M")
            start_dt = datetime.combine(date.today(), periods[0].starts_at)
            end_dt = datetime.combine(date.today(), periods[-1].ends_at)
            diff = end_dt - start_dt
            hours, remainder = divmod(diff.seconds, 3600)
            minutes = remainder // 60
            d.total_duration = f"{hours}س {minutes}د"
        else:
            d.first_period_time = "--:--"
            d.last_period_time = "--:--"
            d.total_duration = "--:--"
        total_periods += d.periods_count

    avg_periods = total_periods / len(days) if days else 0
    max_periods_day = max(days, key=lambda d: d.periods_count) if days else None
    min_periods_day = min(days, key=lambda d: d.periods_count) if days else None

    ctx = {
        "days": days,
        "total_periods": total_periods,
        "avg_periods": avg_periods,
        "max_periods_day": max_periods_day,
        "min_periods_day": min_periods_day,
    }
    return render(request, "dashboard/days_list.html", ctx)


@manager_required
@transaction.atomic
def day_edit(request, weekday: int):
    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم غير موجود في قائمة الأيام الدراسية.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)
    day.day_name = WEEKDAY_MAP[weekday]

    if request.method == "POST":
        form = DayScheduleForm(request.POST, instance=day)
        p_formset = PeriodFormSet(request.POST, instance=day, prefix="p")
        b_formset = BreakFormSet(request.POST, instance=day, prefix="b")

        form_valid = form.is_valid()
        p_valid = p_formset.is_valid()
        b_valid = b_formset.is_valid()

        if form_valid and p_valid and b_valid:
            form.save()
            p_formset.save()
            b_formset.save()
            messages.success(request, "تم حفظ جدول اليوم بنجاح.")
            return redirect("dashboard:days_list")

        detail = _collect_form_errors(form, p_formset, b_formset)
        if not detail:
            detail = "تحقق من الأوقات: يوجد حقول ناقصة/مكررة أو تداخلات زمنية."
        messages.error(request, detail)
    else:
        form = DayScheduleForm(instance=day)
        p_formset = PeriodFormSet(instance=day, prefix="p")
        b_formset = BreakFormSet(instance=day, prefix="b")

    return render(
        request,
        "dashboard/day_edit.html",
        {
            "day": day,
            "form": form,
            "p_formset": p_formset,
            "b_formset": b_formset,
        },
    )


@manager_required
@transaction.atomic
def day_autofill(request, weekday: int):
    allowed = set(WEEKDAY_MAP.keys())
    if weekday not in allowed:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسي.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)
    if request.method != "POST":
        return redirect("dashboard:day_edit", weekday=weekday)

    try:
        start_time_str = request.POST.get("start_time", "07:00:00")
        period_minutes = _to_int(request.POST.get("period_minutes"), 45)
        period_seconds = _to_int(request.POST.get("period_seconds"), 0)
        gap_minutes = _to_int(request.POST.get("gap_minutes"), 0)
        gap_seconds = _to_int(request.POST.get("gap_seconds"), 0)
        break_after = _to_int(request.POST.get("break_after"), 0)
        break_minutes = _to_int(request.POST.get("break_minutes") or request.POST.get("break_duration"), 0)
        break_seconds = _to_int(request.POST.get("break_seconds"), 0)

        start_t = _parse_hhmm_or_hhmmss(start_time_str)

        p_len = timedelta(minutes=period_minutes, seconds=period_seconds)
        gap = timedelta(minutes=gap_minutes, seconds=gap_seconds)
        brk = timedelta(minutes=break_minutes, seconds=break_seconds)

        if p_len.total_seconds() <= 0:
            raise ValueError("طول الحصة يجب أن يكون أكبر من صفر.")

        if not day.periods_count or day.periods_count <= 0:
            messages.error(request, "عدد الحصص لليوم يساوي صفر.")
            return redirect("dashboard:day_edit", weekday=weekday)

        if break_after < 0 or break_after > day.periods_count:
            raise ValueError("قيمة 'الفسحة بعد الحصة رقم' خارج النطاق.")

        periods_mgr = _rev_manager(day, "periods", "period_set")
        breaks_mgr = _rev_manager(day, "breaks", "break_set")

        base_date = timezone.localdate()
        cursor = datetime.combine(base_date, start_t)

        periods_mgr.all().delete()
        breaks_mgr.all().delete()

        break_minutes_final = int(math.ceil(max(0, brk.total_seconds()) / 60.0)) if brk.total_seconds() > 0 else 0

        for i in range(1, day.periods_count + 1):
            start_period = cursor
            end_period = cursor + p_len
            periods_mgr.create(
                index=i,
                starts_at=start_period.time(),
                ends_at=end_period.time(),
            )
            cursor = end_period

            if break_minutes_final > 0 and break_after == i:
                breaks_mgr.create(
                    label="فسحة",
                    starts_at=cursor.time(),
                    duration_min=break_minutes_final,
                )
                cursor += timedelta(minutes=break_minutes_final)

            cursor += gap

        messages.success(request, "تمت التعبئة التلقائية للجدول.")
        return redirect("dashboard:day_edit", weekday=weekday)
    except Exception as e:
        messages.error(request, f"تعذّر تنفيذ التعبئة: {e}")
        return redirect("dashboard:day_edit", weekday=weekday)


@manager_required
@transaction.atomic
def day_toggle(request, weekday: int):
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")

    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم غير صالح.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    day, _ = DaySchedule.objects.get_or_create(settings=settings_obj, weekday=weekday)

    day.is_active = not day.is_active
    day.save()

    status = "تفعيل" if day.is_active else "تعطيل"
    messages.success(request, f"تم {status} يوم {day.get_weekday_display()}.")
    return redirect("dashboard:days_list")


@manager_required
def ann_list(request):
    school = request.user.profile.school
    qs = Announcement.objects.filter(school=school).order_by("-starts_at")
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "dashboard/ann_list.html", {"page": page})


@manager_required
def ann_create(request):
    school = request.user.profile.school
    if request.method == "POST":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            ann = form.save(commit=False)
            ann.school = school
            ann.save()
            messages.success(request, "تم إنشاء التنبيه.")
            return redirect("dashboard:ann_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AnnouncementForm()
    return render(request, "dashboard/ann_form.html", {"form": form, "title": "إنشاء تنبيه"})


@manager_required
def ann_edit(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(Announcement, pk=pk, school=school)
    if request.method == "POST":
        form = AnnouncementForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث التنبيه.")
            return redirect("dashboard:ann_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AnnouncementForm(instance=obj)
    return render(request, "dashboard/ann_form.html", {"form": form, "title": "تعديل تنبيه"})


@manager_required
def ann_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(Announcement, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف التنبيه.")
        return redirect("dashboard:ann_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def exc_list(request):
    school = request.user.profile.school
    qs = Excellence.objects.filter(school=school).order_by("priority", "-start_at")

    now = timezone.now()
    active_count = Excellence.objects.filter(
        Q(school=school)
        & Q(start_at__lte=now)
        & (Q(end_at__isnull=True) | Q(end_at__gt=now))
    ).count()
    expired_count = Excellence.objects.filter(school=school, end_at__lte=now).count()
    max_p = Excellence.objects.filter(school=school).aggregate(m=Max("priority"))["m"] or 0

    page = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/exc_list.html",
        {
            "page": page,
            "active_count": active_count,
            "expired_count": expired_count,
            "max_priority": max_p,
        },
    )


@manager_required
def exc_create(request):
    school = request.user.profile.school
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES)
        if form.is_valid():
            exc = form.save(commit=False)
            exc.school = school
            exc.save()
            messages.success(request, "تم إضافة بطاقة التميز.")
            return redirect("dashboard:exc_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = ExcellenceForm()
    return render(
        request,
        "dashboard/exc_form.html",
        {
            "form": form,
            "title": "إضافة تميز",
        },
    )


@manager_required
def exc_edit(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بطاقة التميز.")
            return redirect("dashboard:exc_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = ExcellenceForm(instance=obj)
    return render(
        request,
        "dashboard/exc_form.html",
        {
            "form": form,
            "title": "تعديل تميز",
        },
    )


@manager_required
def exc_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف البطاقة.")
        return redirect("dashboard:exc_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def standby_list(request):
    school = request.user.profile.school
    qs = StandbyAssignment.objects.filter(school=school).order_by("-date", "period_index")

    today = timezone.localdate()
    today_count = StandbyAssignment.objects.filter(school=school, date=today).count()
    teachers_count = (
        StandbyAssignment.objects.filter(school=school).values("teacher_name").distinct().count()
    )
    classes_count = (
        StandbyAssignment.objects.filter(school=school).values("class_name").distinct().count()
    )

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/standby_list.html",
        {
            "page": page,
            "today_count": today_count,
            "teachers_count": teachers_count,
            "classes_count": classes_count,
        },
    )


@manager_required
def standby_create(request):
    school = request.user.profile.school
    if request.method == "POST":
        form = StandbyForm(request.POST)
        if form.is_valid():
            standby = form.save(commit=False)
            standby.school = school
            standby.save()
            messages.success(request, "تم إضافة تكليف الانتظار.")
            return redirect("dashboard:standby_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = StandbyForm()
    return render(
        request,
        "dashboard/standby_form.html",
        {
            "form": form,
            "title": "إضافة تكليف",
        },
    )


@manager_required
def standby_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(StandbyAssignment, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم الحذف.")
        return redirect("dashboard:standby_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def standby_import(request):
    school = request.user.profile.school
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith(".csv"):
            messages.error(request, "فضلاً أرفق ملف CSV صحيح.")
            return redirect("dashboard:standby_list")

        raw_data = f.read()
        decoded_file = None

        for enc in ["utf-8-sig", "windows-1256", "iso-8859-1"]:
            try:
                decoded_file = raw_data.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if decoded_file is None:
            decoded_file = raw_data.decode("utf-8", errors="replace")

        data = io.StringIO(decoded_file)
        reader = csv.DictReader(data)
        count = 0

        for row in reader:
            try:
                raw_date = (row.get("date") or "").strip()
                try:
                    parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                except ValueError:
                    parsed_date = datetime.strptime(raw_date, "%d/%m/%Y").date()

                period_index = int(row.get("period_index") or 0)
                if period_index <= 0:
                    raise ValueError("period_index غير صالح")

                StandbyAssignment.objects.create(
                    school=school,
                    date=parsed_date,
                    period_index=period_index,
                    class_name=row.get("class_name", ""),
                    teacher_name=row.get("teacher_name", ""),
                    notes=row.get("notes", "") or "",
                )
                count += 1
            except Exception:
                continue

        messages.success(request, f"تم استيراد {count} سجل.")
        return redirect("dashboard:standby_list")

    return render(request, "dashboard/standby_import.html")


@manager_required
def screen_list(request):
    school = request.user.profile.school
    qs = DisplayScreen.objects.filter(school=school).order_by("-created_at")
    return render(request, "dashboard/screen_list.html", {"screens": qs})


@manager_required
def screen_create(request):
    school = request.user.profile.school
    if request.method == "POST":
        form = DisplayScreenForm(request.POST)
        if form.is_valid():
            screen = form.save(commit=False)
            screen.school = school
            screen.save()
            messages.success(request, "تم إضافة شاشة جديدة.")
            return redirect("dashboard:screen_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = DisplayScreenForm()

    return render(
        request,
        "dashboard/screen_form.html",
        {
            "form": form,
            "title": "إضافة شاشة",
        },
    )


@manager_required
def screen_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(DisplayScreen, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف الشاشة.")
        return redirect("dashboard:screen_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
@transaction.atomic
def day_clear(request, weekday: int):
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")

    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسية.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    periods_mgr = getattr(day, "periods", getattr(day, "period_set"))
    breaks_mgr = getattr(day, "breaks", getattr(day, "break_set"))

    periods_mgr.all().delete()
    breaks_mgr.all().delete()

    messages.success(request, "تم مسح جميع الحصص والفسح لهذا اليوم.")
    return redirect("dashboard:day_edit", weekday=weekday)


@manager_required
@transaction.atomic
def day_reindex(request, weekday: int):
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")

    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسية.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    periods_mgr = getattr(day, "periods", getattr(day, "period_set"))
    periods = list(periods_mgr.all())

    periods.sort(key=lambda p: (p.starts_at or time.min, p.ends_at or time.min))

    for i, p in enumerate(periods, start=1):
        if p.index != i:
            p.index = i
            p.save(update_fields=["index"])

    messages.success(request, "تمت إعادة ترقيم الحصص حسب الترتيب الزمني (١..ن).")
    return redirect("dashboard:day_edit", weekday=weekday)


@manager_required
def lessons_list(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    lessons = []
    if settings_obj:
        lessons = (
            settings_obj.class_lessons.select_related("school_class", "subject", "teacher")
            .order_by("weekday", "period_index", "school_class__name")
        )
    search = (request.GET.get("search") or "").strip()
    day = (request.GET.get("day") or "").strip()
    if search and lessons:
        lessons = lessons.filter(
            models.Q(school_class__name__icontains=search)
            | models.Q(subject__name__icontains=search)
            | models.Q(teacher__name__icontains=search)
        )
    if day.isdigit() and lessons:
        lessons = lessons.filter(weekday=int(day))
    return render(request, "dashboard/lessons_list.html", {"lessons": lessons})


@manager_required
def lesson_create(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:lessons_list")
    if request.method == "POST":
        form = LessonForm(request.POST)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.settings = settings_obj
            lesson.save()
            messages.success(request, "تمت إضافة الحصة بنجاح.")
            return redirect("dashboard:lessons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = LessonForm()
    return render(request, "dashboard/lesson_form.html", {"form": form, "title": "إضافة حصة"})


@manager_required
def lesson_edit(request, pk: int):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    obj = get_object_or_404(ClassLesson, pk=pk, settings=settings_obj)
    if request.method == "POST":
        form = LessonForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تعديل الحصة بنجاح.")
            return redirect("dashboard:lessons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = LessonForm(instance=obj)
    return render(request, "dashboard/lesson_form.html", {"form": form, "title": "تعديل حصة"})


@manager_required
def lesson_delete(request, pk: int):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    obj = get_object_or_404(ClassLesson, pk=pk, settings=settings_obj)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف الحصة.")
        return redirect("dashboard:lessons_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def school_data(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    classes = settings_obj.school_classes.all() if settings_obj else []
    subjects = Subject.objects.all()
    teachers = Teacher.objects.all()
    if request.method == "POST":
        if "name" in request.POST:
            name = request.POST["name"].strip()
            if request.path.endswith("add_class") and settings_obj:
                SchoolClass.objects.create(settings=settings_obj, name=name)
            elif request.path.endswith("add_subject"):
                Subject.objects.create(name=name)
            elif request.path.endswith("add_teacher"):
                Teacher.objects.create(name=name)
        elif request.path.startswith("/dashboard/delete_class/"):
            pk = int(request.path.split("/")[-1])
            SchoolClass.objects.filter(pk=pk).delete()
        elif request.path.startswith("/dashboard/delete_subject/"):
            pk = int(request.path.split("/")[-1])
            Subject.objects.filter(pk=pk).delete()
        elif request.path.startswith("/dashboard/delete_teacher/"):
            pk = int(request.path.split("/")[-1])
            Teacher.objects.filter(pk=pk).delete()
        return redirect("dashboard:school_data")
    return render(
        request,
        "dashboard/school_data.html",
        {
            "classes": classes,
            "subjects": subjects,
            "teachers": teachers,
        },
    )


@manager_required
def add_class(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if request.method == "POST" and settings_obj:
        name = (request.POST.get("name") or "").strip()
        if name:
            SchoolClass.objects.create(settings=settings_obj, name=name)
    return redirect("dashboard:school_data")


@manager_required
def delete_class(request, pk):
    SchoolClass.objects.filter(pk=pk).delete()
    return redirect("dashboard:school_data")


@manager_required
def add_subject(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Subject.objects.create(name=name)
    return redirect("dashboard:school_data")


@manager_required
def delete_subject(request, pk):
    Subject.objects.filter(pk=pk).delete()
    return redirect("dashboard:school_data")


@manager_required
def add_teacher(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Teacher.objects.create(name=name)
    return redirect("dashboard:school_data")


@manager_required
def delete_teacher(request, pk):
    Teacher.objects.filter(pk=pk).delete()
    return redirect("dashboard:school_data")


@manager_required
def timetable_day_view(request):
    user = request.user
    profile = getattr(user, "profile", None)
    school = getattr(profile, "school", None)

    if school is None:
        messages.error(request, "لا يوجد مدرسة مرتبطة بحسابك.")
        return redirect("dashboard:index")

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    weekdays_choices = list(SCHOOL_WEEK)
    default_weekday = weekdays_choices[0][0] if weekdays_choices else 0

    if request.method == "GET":
        weekday_param = request.GET.get("weekday")
        class_param = request.GET.get("class_id")
    else:
        weekday_param = request.POST.get("weekday")
        class_param = request.POST.get("class_id")

    try:
        weekday = int(weekday_param) if weekday_param not in (None, "") else int(default_weekday)
    except (TypeError, ValueError):
        weekday = int(default_weekday)

    classes_qs = settings_obj.school_classes.all().order_by("name")

    selected_class = None
    if classes_qs.exists():
        try:
            if class_param not in (None, ""):
                selected_class = classes_qs.get(pk=int(class_param))
            else:
                selected_class = classes_qs.first()
        except (ValueError, SchoolClass.DoesNotExist):
            selected_class = classes_qs.first()
    selected_class_id = selected_class.id if selected_class else None

    periods_qs = Period.objects.filter(day__settings=settings_obj, day__weekday=weekday).order_by("index")

    subjects_qs = Subject.objects.all().order_by("name")
    teachers_qs = Teacher.objects.all().order_by("name")

    if selected_class is not None:
        existing_lessons_qs = ClassLesson.objects.filter(
            settings=settings_obj,
            weekday=weekday,
            school_class=selected_class,
        ).select_related("subject", "teacher")
    else:
        existing_lessons_qs = ClassLesson.objects.none()

    lessons_map: dict[int, ClassLesson] = {}
    for lesson in existing_lessons_qs:
        lessons_map[lesson.period_index] = lesson

    if request.method == "POST" and selected_class is not None:
        created_count = 0
        updated_count = 0
        deleted_count = 0

        subjects_by_id = {s.id: s for s in subjects_qs}
        teachers_by_id = {t.id: t for t in teachers_qs}

        with transaction.atomic():
            for period in periods_qs:
                period_index = period.index
                existing_lesson = lessons_map.get(period_index)

                subject_field = f"subject-{selected_class.id}-{period_index}"
                teacher_field = f"teacher-{selected_class.id}-{period_index}"

                subject_raw = (request.POST.get(subject_field) or "").strip()
                teacher_raw = (request.POST.get(teacher_field) or "").strip()

                subject_obj = None
                teacher_obj = None

                if subject_raw:
                    try:
                        subject_id = int(subject_raw)
                        subject_obj = subjects_by_id.get(subject_id)
                    except (TypeError, ValueError):
                        subject_obj = None

                if teacher_raw:
                    try:
                        teacher_id = int(teacher_raw)
                        teacher_obj = teachers_by_id.get(teacher_id)
                    except (TypeError, ValueError):
                        teacher_obj = None

                if subject_obj is None and teacher_obj is None:
                    if existing_lesson is not None:
                        existing_lesson.delete()
                        deleted_count += 1
                    continue

                if existing_lesson is not None:
                    if subject_obj is None:
                        subject_obj = existing_lesson.subject
                    if teacher_obj is None:
                        teacher_obj = existing_lesson.teacher

                if subject_obj is None or teacher_obj is None:
                    continue

                if existing_lesson is None:
                    ClassLesson.objects.create(
                        settings=settings_obj,
                        school_class=selected_class,
                        weekday=weekday,
                        period_index=period_index,
                        subject=subject_obj,
                        teacher=teacher_obj,
                        is_active=True,
                    )
                    created_count += 1
                else:
                    changed = False
                    if existing_lesson.subject_id != subject_obj.id:
                        existing_lesson.subject = subject_obj
                        changed = True
                    if existing_lesson.teacher_id != teacher_obj.id:
                        existing_lesson.teacher = teacher_obj
                        changed = True
                    if not existing_lesson.is_active:
                        existing_lesson.is_active = True
                        changed = True
                    if changed:
                        existing_lesson.save()
                        updated_count += 1

        if created_count or updated_count or deleted_count:
            msg_parts = []
            if created_count:
                msg_parts.append(f"تم إنشاء {created_count} حصة جديدة.")
            if updated_count:
                msg_parts.append(f"تم تحديث {updated_count} حصة.")
            if deleted_count:
                msg_parts.append(f"تم حذف {deleted_count} حصة فارغة.")
            messages.success(request, " ".join(msg_parts))
        else:
            messages.info(request, "لم يتم رصد أي تغييرات في جدول هذا الفصل.")

        url = reverse("dashboard:timetable_day")
        url = f"{url}?weekday={weekday}&class_id={selected_class.id}"
        return redirect(url)

    rows: list[dict] = []
    for period in periods_qs:
        lesson = lessons_map.get(period.index)
        rows.append(
            {
                "period": period,
                "subject_id": lesson.subject_id if lesson else None,
                "teacher_id": lesson.teacher_id if lesson else None,
            }
        )

    context = {
        "school": school,
        "settings": settings_obj,
        "weekdays": weekdays_choices,
        "weekday": weekday,
        "classes": classes_qs,
        "selected_class": selected_class,
        "selected_class_id": selected_class_id,
        "periods": periods_qs,
        "rows": rows,
        "subjects": subjects_qs,
        "teachers": teachers_qs,
    }
    return render(request, "dashboard/timetable_day.html", context)


@manager_required
def timetable_week_view(request):
    user = request.user
    profile = getattr(user, "profile", None)
    school = getattr(profile, "school", None)

    if school is None:
        messages.error(request, "لا يوجد مدرسة مرتبطة بحسابك.")
        return redirect("dashboard:index")

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    class_param = request.GET.get("class_id")
    classes_qs = settings_obj.school_classes.all().order_by("name")

    if not classes_qs.exists():
        messages.error(request, "لا توجد فصول مسجلة لهذه المدرسة.")
        return redirect("dashboard:timetable_day")

    selected_class = None
    try:
        if class_param not in (None, ""):
            selected_class = classes_qs.get(pk=int(class_param))
        else:
            selected_class = classes_qs.first()
    except (ValueError, SchoolClass.DoesNotExist):
        selected_class = classes_qs.first()

    if selected_class is None:
        messages.error(request, "تعذر تحديد الفصل.")
        return redirect("dashboard:timetable_day")

    days_data = []

    for weekday, label in SCHOOL_WEEK:
        day_periods = Period.objects.filter(day__settings=settings_obj, day__weekday=weekday).order_by("index")

        lessons_qs = ClassLesson.objects.filter(
            settings=settings_obj,
            school_class=selected_class,
            weekday=weekday,
        ).select_related("subject", "teacher")

        lessons_map = {lesson.period_index: lesson for lesson in lessons_qs}

        rows = []
        for period in day_periods:
            lesson = lessons_map.get(period.index)
            rows.append(
                {
                    "period": period,
                    "lesson": lesson,
                    "subject_name": lesson.subject.name if lesson and lesson.subject else "",
                    "teacher_name": lesson.teacher.name if lesson and lesson.teacher else "",
                }
            )

        days_data.append(
            {
                "weekday": weekday,
                "label": label,
                "rows": rows,
            }
        )

    context = {
        "school": school,
        "settings": settings_obj,
        "selected_class": selected_class,
        "days_data": days_data,
    }
    return render(request, "dashboard/timetable_week.html", context)


@manager_required
def timetable_export_csv(request):
    user = request.user
    profile = getattr(user, "profile", None)
    school = getattr(profile, "school", None)

    if school is None:
        messages.error(request, "لا يوجد مدرسة مرتبطة بحسابك.")
        return redirect("dashboard:index")

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    class_param = request.GET.get("class_id")
    if not class_param:
        messages.error(request, "لم يتم تحديد الفصل المطلوب للتصدير.")
        return redirect("dashboard:timetable_day")

    try:
        school_class = settings_obj.school_classes.get(pk=int(class_param))
    except (ValueError, SchoolClass.DoesNotExist):
        messages.error(request, "الفصل المحدد غير موجود.")
        return redirect("dashboard:timetable_day")

    periods_qs = Period.objects.filter(day__settings=settings_obj).select_related("day")
    period_map: dict[tuple[int, int], Period] = {}
    for p in periods_qs:
        key = (p.day.weekday, p.index)
        period_map[key] = p

    lessons = (
        ClassLesson.objects.filter(settings=settings_obj, school_class=school_class)
        .select_related("subject", "teacher")
        .order_by("weekday", "period_index")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"timetable_{school_class.name}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")

    writer = csv.writer(response)
    writer.writerow(["اليوم", "رقم الحصة", "وقت البداية", "وقت النهاية", "المادة", "المعلم"])

    for lesson in lessons:
        key = (lesson.weekday, lesson.period_index)
        period = period_map.get(key)
        day_label = WEEKDAY_MAP.get(lesson.weekday, str(lesson.weekday))
        start_str = ""
        end_str = ""
        if period is not None:
            if period.starts_at:
                start_str = period.starts_at.strftime("%H:%M")
            if period.ends_at:
                end_str = period.ends_at.strftime("%H:%M")

        subject_name = lesson.subject.name if lesson.subject else ""
        teacher_name = lesson.teacher.name if lesson.teacher else ""

        writer.writerow(
            [
                day_label,
                lesson.period_index,
                start_str,
                end_str,
                subject_name,
                teacher_name,
            ]
        )

    return response
