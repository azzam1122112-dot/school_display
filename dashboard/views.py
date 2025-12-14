from __future__ import annotations

from datetime import datetime, date, time, timedelta
import csv
import io
import math

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    update_session_auth_hash,
    get_user_model,
)
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Q, Max
from django.http import HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

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
    SystemUserCreateForm,
    SystemUserUpdateForm,
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
from core.models import DisplayScreen, School, UserProfile
from subscriptions.forms import SchoolSubscriptionForm
from subscriptions.models import SchoolSubscription

UserModel = get_user_model()

# ====================
# ثوابت وأدوات مساعدة
# ====================

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
    """
    تجميع رسائل الأخطاء من الفورمات والفورم ست في رسالة نصية واحدة.
    """
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
            for f in getattr(obj, "forms", []):
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
    """
    إرجاع المدير الصحيح لعلاقة عكسية (periods أو period_set مثلاً).
    """
    mgr = getattr(obj, preferred, None)
    if mgr is None:
        mgr = getattr(obj, fallback)
    return mgr


def _parse_hhmm_or_hhmmss(s: str) -> time:
    """
    تحويل نص HH:MM أو HH:MM:SS إلى كائن time مع رسائل خطأ واضحة.
    """
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
    """
    تحويل نص إلى int مع قيمة افتراضية واختيار منع القيم السالبة.
    """
    try:
        x = int(val) if val not in (None, "") else default
    except (TypeError, ValueError):
        x = default
    if not allow_negative and x < 0:
        raise ValueError("القيم لا يجوز أن تكون سالبة.")
    return x


# ==========================================================
# ✅ Helpers جديدة/محدّثة: ملف شخصي + مدرسة نشطة بشكل موحّد
# ==========================================================

def _get_or_create_profile(user) -> UserProfile:
    """
    ضمان وجود UserProfile للمستخدم (خصوصًا في Render حيث قد تُنشأ حسابات بدون Profile).
    """
    profile = getattr(user, "profile", None)
    if profile:
        return profile
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def get_active_school_or_redirect(request):
    """
    إرجاع المدرسة النشطة للمستخدم.
    - يعتمد على profile.active_school أولاً
    - ثم أول مدرسة في profile.schools
    - إذا لا يوجد أي مدرسة: رسالة وتوجيه للوحة (أو PermissionDenied حسب رغبتك)
    """
    if not request.user.is_authenticated:
        return None, redirect("dashboard:login")

    profile = _get_or_create_profile(request.user)

    # 1) active_school إن وجدت
    active_school = getattr(profile, "active_school", None)
    if active_school:
        return active_school, None

    # 2) أول مدرسة في m2m إن وجدت
    schools_qs = profile.schools.order_by("id")
    if schools_qs.exists():
        profile.active_school = schools_qs.first()
        profile.save(update_fields=["active_school"])
        messages.info(request, f"تم تعيين المدرسة النشطة تلقائيًا: {profile.active_school.name}")
        return profile.active_school, None

    # 3) لا توجد مدارس مرتبطة
    messages.error(request, "الملف الشخصي غير مرتبط بأي مدرسة.")
    return None, redirect("dashboard:index")


def require_active_school(request) -> School:
    """
    نسخة صارمة: ترمي PermissionDenied إذا لا توجد مدرسة.
    مفيدة للصفحات التي يجب منعها بالكامل بدل إعادة توجيه.
    """
    school, response = get_active_school_or_redirect(request)
    if response:
        raise PermissionDenied("الملف الشخصي غير مرتبط بأي مدرسة.")
    return school


# ======================
# مصادقة ولوحة المدير
# ======================

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
    """
    تسجيل دخول بحساب تجريبي مع بيانات مدرسة تجريبية.
    - إذا لم يوجد المستخدم demo_user يتم إنشاؤه.
    - إذا لم توجد مدرسة تجريبية يتم إنشاؤها.
    - يتم إنشاء UserProfile يربط المستخدم بالمدرسة التجريبية.
    """
    DEMO_USERNAME = "demo_user"
    DEMO_SCHOOL_SLUG = "demo-school"

    demo_school, _ = School.objects.get_or_create(
        slug=DEMO_SCHOOL_SLUG,
        defaults={
            "name": "مدرسة تجريبية",
            "is_active": True,
        },
    )

    demo_user, created = UserModel.objects.get_or_create(
        username=DEMO_USERNAME,
        defaults={
            "first_name": "حساب",
            "last_name": "تجريبي",
            "email": "demo@example.com",
            "is_active": True,
        },
    )

    if created:
        demo_user.set_password(get_random_string(12))
        demo_user.save()

    profile = _get_or_create_profile(demo_user)
    if demo_school not in profile.schools.all():
        profile.schools.add(demo_school)
    if profile.active_school != demo_school:
        profile.active_school = demo_school
        profile.save(update_fields=["active_school"])

    login(request, demo_user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, "تم تسجيل دخولك بحساب تجريبي. البيانات هنا لأغراض العرض فقط.")
    return redirect("dashboard:index")


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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    today = timezone.localdate()
    stats = {
        "ann_count": Announcement.objects.filter(school=school).count(),
        "exc_count": Excellence.objects.filter(school=school).count(),
        "standby_today": StandbyAssignment.objects.filter(school=school, date=today).count(),
    }

    settings_obj = SchoolSettings.objects.filter(school=school).first()

    subscription = (
        SchoolSubscription.objects
        .filter(school=school)
        .order_by("-starts_at")
        .first()
    )

    return render(
        request,
        "dashboard/index.html",
        {
            "stats": stats,
            "settings": settings_obj,
            "subscription": subscription,
        },
    )


# ======================
# إعدادات المدرسة
# ======================

@manager_required
def school_settings(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    obj, _created = SchoolSettings.objects.get_or_create(
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


# ======================
# إدارة أيام الجدول
# ======================

@manager_required
def days_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    existing = set(
        DaySchedule.objects.filter(
            settings=settings_obj, weekday__in=WEEKDAY_MAP.keys()
        ).values_list("weekday", flat=True)
    )
    for w in WEEKDAY_MAP.keys():
        if w not in existing:
            DaySchedule.objects.create(
                settings=settings_obj,
                weekday=w,
                periods_count=7 if w in (0, 1) else 6,
            )

    days = list(
        DaySchedule.objects.filter(
            settings=settings_obj, weekday__in=WEEKDAY_MAP.keys()
        )
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

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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
        break_minutes = _to_int(
            request.POST.get("break_minutes") or request.POST.get("break_duration"), 0
        )
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

        break_minutes_final = (
            int(math.ceil(max(0, brk.total_seconds()) / 60.0))
            if brk.total_seconds() > 0
            else 0
        )

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

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    day, _ = DaySchedule.objects.get_or_create(settings=settings_obj, weekday=weekday)

    day.is_active = not day.is_active
    day.save()

    status = "تفعيل" if day.is_active else "تعطيل"
    messages.success(request, f"تم {status} يوم {day.get_weekday_display()}.")
    return redirect("dashboard:days_list")


# ======================
# التنبيهات وبطاقات التميز
# ======================

@manager_required
def ann_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    qs = Announcement.objects.filter(school=school).order_by("-starts_at")
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "dashboard/ann_list.html", {"page": page})


@manager_required
def ann_create(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(Announcement, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف التنبيه.")
        return redirect("dashboard:ann_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def exc_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
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
    return render(request, "dashboard/exc_form.html", {"form": form, "title": "إضافة تميز"})


@manager_required
def exc_edit(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
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
    return render(request, "dashboard/exc_form.html", {"form": form, "title": "تعديل تميز"})


@manager_required
def exc_delete(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف البطاقة.")
        return redirect("dashboard:exc_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


# ======================
# حصص الانتظار
# ======================

@manager_required
def standby_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    qs = StandbyAssignment.objects.filter(school=school).order_by("-date", "period_index")

    today = timezone.localdate()
    today_count = StandbyAssignment.objects.filter(school=school, date=today).count()
    teachers_count = (
        StandbyAssignment.objects.filter(school=school)
        .values("teacher_name").distinct().count()
    )
    classes_count = (
        StandbyAssignment.objects.filter(school=school)
        .values("class_name").distinct().count()
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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    if request.method == "POST":
        form = StandbyForm(request.POST, school=school)
        if form.is_valid():
            standby = form.save(commit=False)
            standby.school = school
            standby.save()
            messages.success(request, "تم إضافة تكليف الانتظار.")
            return redirect("dashboard:standby_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = StandbyForm(school=school)

    return render(request, "dashboard/standby_form.html", {"form": form, "title": "إضافة تكليف"})


@manager_required
def standby_delete(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(StandbyAssignment, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم الحذف.")
        return redirect("dashboard:standby_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


@manager_required
def standby_import(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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
        new_standby_assignments = []

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

                new_standby_assignments.append(
                    StandbyAssignment(
                        school=school,
                        date=parsed_date,
                        period_index=period_index,
                        class_name=row.get("class_name", ""),
                        teacher_name=row.get("teacher_name", ""),
                        notes=row.get("notes", "") or "",
                    )
                )
            except Exception:
                continue

        if new_standby_assignments:
            StandbyAssignment.objects.bulk_create(new_standby_assignments)
            count = len(new_standby_assignments)
        else:
            count = 0

        messages.success(request, f"تم استيراد {count} سجل.")
        return redirect("dashboard:standby_list")

    return render(request, "dashboard/standby_import.html")


# ======================
# شاشات العرض
# ======================

@manager_required
def screen_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    qs = DisplayScreen.objects.filter(school=school).order_by("-created_at")
    can_create_screen = qs.count() == 0
    show_screen_limit_message = not can_create_screen
    return render(
        request,
        "dashboard/screen_list.html",
        {
            "screens": qs,
            "can_create_screen": can_create_screen,
            "show_screen_limit_message": show_screen_limit_message,
        },
    )


@manager_required
def screen_create(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    if DisplayScreen.objects.filter(school=school).exists():
        messages.warning(request, "لا يمكن إنشاء أكثر من شاشة واحدة لهذه المدرسة.")
        return redirect("dashboard:screen_list")

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

    return render(request, "dashboard/screen_form.html", {"form": form, "title": "إضافة شاشة"})


@manager_required
def screen_delete(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(DisplayScreen, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف الشاشة.")
        return redirect("dashboard:screen_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


# ======================
# أدوات إضافية على الأيام
# ======================

@manager_required
@transaction.atomic
def day_clear(request, weekday: int):
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")

    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسية.")
        return redirect("dashboard:days_list")

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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


# ======================
# الحصص (ClassLesson)
# ======================

@manager_required
def lessons_list(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:lessons_list")

    if request.method == "POST":
        form = LessonForm(request.POST)
    else:
        form = LessonForm()

    form.fields["school_class"].queryset = SchoolClass.objects.filter(settings__school=school).order_by("name")
    form.fields["subject"].queryset = Subject.objects.filter(school=school).order_by("name")
    form.fields["teacher"].queryset = Teacher.objects.filter(school=school).order_by("name")

    if request.method == "POST":
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.settings = settings_obj
            lesson.save()
            messages.success(request, "تمت إضافة الحصة بنجاح.")
            return redirect("dashboard:lessons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")

    return render(request, "dashboard/lesson_form.html", {"form": form, "title": "إضافة حصة"})


@manager_required
def lesson_edit(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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

    form.fields["school_class"].queryset = SchoolClass.objects.filter(settings__school=school).order_by("name")
    form.fields["subject"].queryset = Subject.objects.filter(school=school).order_by("name")
    form.fields["teacher"].queryset = Teacher.objects.filter(school=school).order_by("name")

    return render(request, "dashboard/lesson_form.html", {"form": form, "title": "تعديل حصة"})


@manager_required
def lesson_delete(request, pk: int):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    obj = get_object_or_404(ClassLesson, pk=pk, settings=settings_obj)

    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف الحصة.")
        return redirect("dashboard:lessons_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


# ======================
# بيانات المدرسة (فصول/مواد/معلمين)
# ======================

@manager_required
def school_data(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()

    if settings_obj:
        classes = settings_obj.school_classes.all().order_by("name")
    else:
        classes = SchoolClass.objects.none()

    subjects = Subject.objects.filter(school=school).order_by("name")
    teachers = Teacher.objects.filter(school=school).order_by("name")

    if request.method == "POST":
        # ملاحظة: من الأفضل فصل هذه العمليات لواجهات مستقلة، لكن نحافظ على السلوك الحالي
        if "name" in request.POST:
            name = (request.POST.get("name") or "").strip()
            if name:
                if request.path.endswith("add_class") and settings_obj:
                    SchoolClass.objects.create(settings=settings_obj, name=name)
                elif request.path.endswith("add_subject"):
                    Subject.objects.create(school=school, name=name)
                elif request.path.endswith("add_teacher"):
                    Teacher.objects.create(school=school, name=name)

        elif request.path.startswith("/dashboard/delete_class/") and settings_obj:
            pk_raw = request.path.rstrip("/").split("/")[-1]
            try:
                pk = int(pk_raw)
            except (TypeError, ValueError):
                pk = None
            if pk is not None:
                SchoolClass.objects.filter(pk=pk, settings=settings_obj).delete()

        elif request.path.startswith("/dashboard/delete_subject/"):
            pk_raw = request.path.rstrip("/").split("/")[-1]
            try:
                pk = int(pk_raw)
            except (TypeError, ValueError):
                pk = None
            if pk is not None:
                Subject.objects.filter(pk=pk, school=school).delete()

        elif request.path.startswith("/dashboard/delete_teacher/"):
            pk_raw = request.path.rstrip("/").split("/")[-1]
            try:
                pk = int(pk_raw)
            except (TypeError, ValueError):
                pk = None
            if pk is not None:
                Teacher.objects.filter(pk=pk, school=school).delete()

        return redirect("dashboard:school_data")

    return render(
        request,
        "dashboard/school_data.html",
        {"classes": classes, "subjects": subjects, "teachers": teachers},
    )


@manager_required
def add_class(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if request.method == "POST" and settings_obj:
        name = (request.POST.get("name") or "").strip()
        if name:
            SchoolClass.objects.create(settings=settings_obj, name=name)
    return redirect("dashboard:school_data")


@manager_required
def delete_class(request, pk):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    SchoolClass.objects.filter(pk=pk, settings__school=school).delete()
    return redirect("dashboard:school_data")


@manager_required
def add_subject(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Subject.objects.create(school=school, name=name)
    return redirect("dashboard:school_data")


@manager_required
def delete_subject(request, pk):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    Subject.objects.filter(pk=pk, school=school).delete()
    return redirect("dashboard:school_data")


@manager_required
def add_teacher(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Teacher.objects.create(school=school, name=name)
    return redirect("dashboard:school_data")


# ======================
# جداول الحصص (يوم/أسبوع/تصدير)
# ======================

@manager_required
def timetable_day_view(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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
    subjects_qs = Subject.objects.filter(school=school).order_by("name")
    teachers_qs = Teacher.objects.filter(school=school).order_by("name")

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
            {"period": period, "subject_id": lesson.subject_id if lesson else None, "teacher_id": lesson.teacher_id if lesson else None}
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
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    class_param = request.GET.get("class_id")
    classes_qs = settings_obj.school_classes.all().order_by("name")

    if not classes_qs.exists():
        messages.error(request, "لا توجد فصول مسجلة لهذه المدرسة.")
        return redirect("dashboard:timetable_day")

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

    all_periods_qs = Period.objects.filter(
        day__settings=settings_obj, day__weekday__in=WEEKDAY_MAP.keys()
    ).order_by("day__weekday", "index")

    periods_by_weekday: dict[int, list[Period]] = {}
    for p in all_periods_qs:
        periods_by_weekday.setdefault(p.day.weekday, []).append(p)

    all_lessons_qs = ClassLesson.objects.filter(
        settings=settings_obj,
        school_class=selected_class,
        weekday__in=WEEKDAY_MAP.keys(),
    ).select_related("subject", "teacher")

    lessons_by_weekday_period: dict[int, dict[int, ClassLesson]] = {}
    for lesson in all_lessons_qs:
        lessons_by_weekday_period.setdefault(lesson.weekday, {})[lesson.period_index] = lesson

    days_data = []
    for weekday, label in SCHOOL_WEEK:
        rows = []
        current_day_periods = periods_by_weekday.get(weekday, [])
        current_day_lessons_map = lessons_by_weekday_period.get(weekday, {})

        for period in current_day_periods:
            lesson = current_day_lessons_map.get(period.index)
            rows.append(
                {
                    "period": period,
                    "lesson": lesson,
                    "subject_name": lesson.subject.name if lesson and lesson.subject else "",
                    "teacher_name": lesson.teacher.name if lesson and lesson.teacher else "",
                }
            )

        days_data.append({"weekday": weekday, "label": label, "rows": rows})

    context = {
        "school": school,
        "settings": settings_obj,
        "selected_class": selected_class,
        "days_data": days_data,
    }
    return render(request, "dashboard/timetable_week.html", context)


@manager_required
def timetable_export_csv(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

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
        period_map[(p.day.weekday, p.index)] = p

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
        period = period_map.get((lesson.weekday, lesson.period_index))
        day_label = WEEKDAY_MAP.get(lesson.weekday, str(lesson.weekday))
        start_str = period.starts_at.strftime("%H:%M") if period and period.starts_at else ""
        end_str = period.ends_at.strftime("%H:%M") if period and period.ends_at else ""

        subject_name = lesson.subject.name if lesson.subject else ""
        teacher_name = lesson.teacher.name if lesson.teacher else ""

        writer.writerow([day_label, lesson.period_index, start_str, end_str, subject_name, teacher_name])

    return response


# =========================
#  لوحة إدارة النظام (SaaS)
# =========================

def superuser_required(view_func):
    """
    يسمح بالدخول فقط للمستخدمين superuser (مدير النظام العام).
    """
    return user_passes_test(lambda u: u.is_superuser, login_url="dashboard:login")(view_func)


class AdminSchoolForm(forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "slug", "is_active"]


@login_required
def switch_school(request, school_id):
    """
    تبديل المدرسة النشطة للمستخدم (ضمن المدارس المرتبطة به).
    """
    profile = _get_or_create_profile(request.user)

    try:
        school = profile.schools.get(pk=school_id)
    except School.DoesNotExist:
        messages.error(request, "المدرسة غير موجودة أو ليس لديك صلاحية الوصول إليها.")
        return redirect("dashboard:index")

    profile.active_school = school
    profile.save(update_fields=["active_school"])
    messages.success(request, f"تم التبديل إلى مدرسة: {school.name}")

    next_url = request.GET.get("next") or "dashboard:index"
    return redirect(next_url)


@superuser_required
def system_admin_dashboard(request):
    school_count = School.objects.count()
    user_count = UserModel.objects.count()

    subs_count = SchoolSubscription.objects.count()
    today = timezone.localdate()
    active_subs = (
        SchoolSubscription.objects
        .filter(status="active")
        .filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=today))
        .count()
    )

    context = {
        "schools_count": school_count,
        "users_count": user_count,
        "subs_count": subs_count,
        "active_subs": active_subs,
    }
    return render(request, "admin/dashboard.html", context)


# =================
# 🏫 إدارة المدارس
# =================

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_schools_list(request):
    q = (request.GET.get("q") or "").strip()
    schools = School.objects.all().order_by("-created_at")

    if q:
        schools = schools.filter(Q(name__icontains=q) | Q(slug__icontains=q))

    return render(request, "admin/schools_list.html", {"schools": schools, "q": q})


@superuser_required
def system_school_create(request):
    if request.method == "POST":
        form = AdminSchoolForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "تمت إضافة المدرسة بنجاح.")
            return redirect("dashboard:system_schools_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AdminSchoolForm()

    return render(request, "admin/school_form.html", {"form": form, "title": "إضافة مدرسة"})


@superuser_required
def system_school_edit(request, pk: int):
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        form = AdminSchoolForm(request.POST, request.FILES, instance=school)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات المدرسة.")
            return redirect("dashboard:system_schools_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AdminSchoolForm(instance=school)

    return render(request, "admin/school_form.html", {"form": form, "title": "تعديل مدرسة", "edit": True})


@superuser_required
def system_school_delete(request, pk: int):
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        school.delete()
        messages.warning(request, f"تم حذف المدرسة: {school.name}")
        return redirect("dashboard:system_schools_list")
    return render(request, "admin/school_confirm_delete.html", {"school": school})


# =================
# 👥 إدارة المستخدمين
# =================

@superuser_required
def system_users_list(request):
    """
    قائمة مستخدمي النظام في لوحة التحكم (مع بحث وترقيم).
    ✅ تحديث البحث ليتوافق مع active_school / schools
    """
    q = (request.GET.get("q") or "").strip()

    qs = (
        UserModel.objects
        .select_related("profile", "profile__active_school")
        .prefetch_related("profile__schools")
        .order_by("-id")
    )

    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(profile__active_school__name__icontains=q)
            | Q(profile__schools__name__icontains=q)
        ).distinct()

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    return render(request, "admin/users_list.html", {"page_obj": page_obj, "q": q})


@superuser_required
def system_user_create(request):
    if request.method == "POST":
        form = SystemUserCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء المستخدم بنجاح.")
            return redirect("dashboard:system_users_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SystemUserCreateForm()

    return render(request, "admin/user_edit.html", {"form": form, "is_create": True})


@superuser_required
def system_user_edit(request, pk: int):
    user = get_object_or_404(UserModel, pk=pk)

    if request.method == "POST":
        form = SystemUserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات المستخدم بنجاح.")
            return redirect("dashboard:system_users_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SystemUserUpdateForm(instance=user)

    return render(
        request,
        "admin/user_edit.html",
        {"form": form, "is_create": False, "user_obj": user},
    )


@superuser_required
def system_user_delete(request, pk: int):
    user = get_object_or_404(UserModel, pk=pk)

    if request.method == "POST":
        username = user.username
        user.delete()
        messages.success(request, f"تم حذف المستخدم {username}.")
        return redirect("dashboard:system_users_list")

    return render(request, "admin/user_delete_confirm.html", {"user_obj": user})


# =====================
# 💳 إدارة الاشتراكات
# =====================

def _get_subscription_model():
    try:
        return apps.get_model("subscriptions", "SchoolSubscription")
    except LookupError:
        return None


@superuser_required
def system_subscriptions_list(request):
    SubModel = _get_subscription_model()
    q = (request.GET.get("q") or "").strip()

    if SubModel is None:
        messages.error(request, "تطبيق الاشتراكات غير موجود.")
        subscriptions = []
    else:
        qs = (
            SubModel.objects
            .select_related("school", "plan")
            .order_by("-starts_at", "-id")
        )
        if q:
            qs = qs.filter(Q(school__name__icontains=q) | Q(plan__name__icontains=q))
        subscriptions = qs

    return render(request, "admin/subscriptions_list.html", {"subscriptions": subscriptions, "q": q})


@superuser_required
def system_subscription_create(request):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    if request.method == "POST":
        form = SchoolSubscriptionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء الاشتراك بنجاح.")
            return redirect("dashboard:system_subscriptions_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSubscriptionForm()

    return render(request, "admin/subscription_form.html", {"form": form, "title": "إضافة اشتراك"})


@superuser_required
def system_subscription_edit(request, pk: int):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    obj = get_object_or_404(SubModel, pk=pk)

    if request.method == "POST":
        form = SchoolSubscriptionForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات الاشتراك.")
            return redirect("dashboard:system_subscriptions_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSubscriptionForm(instance=obj)

    return render(
        request,
        "admin/subscription_form.html",
        {"form": form, "title": "تعديل اشتراك", "edit": True},
    )


@superuser_required
def system_subscription_delete(request, pk: int):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    obj = get_object_or_404(SubModel, pk=pk)

    if request.method == "POST":
        obj.delete()
        messages.warning(request, "تم حذف الاشتراك.")
        return redirect("dashboard:system_subscriptions_list")

    return HttpResponseBadRequest("طريقة غير مدعومة.")


# ==========================
# ✅ اشتراكي (مدرسة المستخدم)
# ==========================

@login_required
def my_subscription(request):
    """
    عرض اشتراك المدرسة للمستخدم الحالي.
    ✅ مُحدّث بالكامل ليتوافق مع active_school / schools (بدل profile.school)
    """
    # المدرسة: active_school ثم أول مدرسة في schools
    profile = _get_or_create_profile(request.user)
    school = profile.active_school or profile.schools.order_by("id").first()

    if not school:
        raise PermissionDenied("الملف الشخصي غير مرتبط بأي مدرسة.")

    subscription = (
        SchoolSubscription.objects
        .filter(school=school)
        .order_by("-starts_at")
        .first()
    )

    today = timezone.localdate()

    status_code = "none"
    status_label = "لا يوجد اشتراك"
    status_badge_class = "bg-rose-50 text-rose-700"

    if subscription is not None:
        if subscription.status == "cancelled":
            status_code = "cancelled"
            status_label = "ملغى"
            status_badge_class = "bg-rose-50 text-rose-700"

        elif subscription.status == "active":
            if subscription.starts_at and subscription.starts_at > today:
                status_code = "upcoming"
                status_label = "لم يبدأ بعد"
                status_badge_class = "bg-amber-50 text-amber-700"
            elif subscription.ends_at and subscription.ends_at < today:
                status_code = "expired"
                status_label = "منتهي"
                status_badge_class = "bg-rose-50 text-rose-700"
            else:
                status_code = "active"
                status_label = "سارية"
                status_badge_class = "bg-emerald-50 text-emerald-700"
        else:
            status_code = subscription.status or "unknown"
            status_label = "غير معروف"
            status_badge_class = "bg-slate-100 text-slate-700"

    return render(
        request,
        "dashboard/my_subscription.html",
        {
            "school": school,
            "subscription": subscription,
            "status_code": status_code,
            "status_label": status_label,
            "status_badge_class": status_badge_class,
            "today": today,
        },
    )
