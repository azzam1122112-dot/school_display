from __future__ import annotations

from datetime import datetime, date, time, timedelta
import csv
import io
import math
import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from django import forms
from django.apps import apps
from django.conf import settings as dj_settings
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
from django.core.exceptions import PermissionDenied, FieldError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max, Q, Sum, Count
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, NoReverseMatch, get_resolver
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from urllib.parse import quote

# ✅ عدّل هذه الاستيرادات حسب أسماء تطبيقاتك الفعلية
from .decorators import manager_required
from .forms import (
    SchoolSettingsForm,
    DayScheduleForm,
    LessonForm,
    AnnouncementForm,
    ExcellenceForm,
    StandbyForm,
    DisplayScreenForm,
    SchoolSubscriptionForm,
    SystemUserCreateForm,
    SystemEmployeeCreateForm,
    SystemUserUpdateForm,
    PeriodFormSet,
    BreakFormSet,
    SubscriptionPlanForm,
    SupportTicketForm,
    CustomerSupportTicketForm,
    TicketCommentForm,
    SubscriptionScreenAddonForm,
    SubscriptionRenewalRequestForm,
    SubscriptionNewRequestForm,
)
from core.models import SubscriptionPlan, SupportTicket, TicketComment

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

UserModel = get_user_model()

WEEKDAY_MAP = {
    0: "الأحد",
    1: "الاثنين",
    2: "الثلاثاء",
    3: "الأربعاء",
    4: "الخميس",
    5: "الجمعة",
    6: "السبت",
}

# أيام الدراسة الافتراضية
SCHOOL_WEEK = [
    (0, "الأحد"),
    (1, "الاثنين"),
    (2, "الثلاثاء"),
    (3, "الأربعاء"),
    (4, "الخميس"),
]
SCHOOL_WEEKDAY_IDS = [w for w, _ in SCHOOL_WEEK]


# ======================
# URL helpers (حل NoReverseMatch للـ namespaces)
# ======================

def _namespace_exists(ns: str) -> bool:
    try:
        return ns in (get_resolver().namespace_dict or {})
    except Exception:
        return False


def _safe_reverse(name: str, *, kwargs: dict | None = None, fallback: str | None = None) -> str:
    """
    reverse آمن: يرجع رابط '#' بدل كسر الصفحة عند NoReverseMatch
    """
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        if fallback:
            try:
                return reverse(fallback, kwargs=kwargs)
            except NoReverseMatch:
                return "#"
        return "#"


# ======================
# Model loader (حل ImportError نهائياً)
# ======================

@lru_cache(maxsize=128)
def _get_model(app_label: str, model_name: str):
    return apps.get_model(app_label, model_name)


def _get_model_first(*candidates: tuple[str, str]):
    """
    جرّب أكثر من مكان للموديل لتفادي تغيّر بنية التطبيقات.
    (مُثبت على هيكل مشروع school_display الحالي)
    """
    last_err = None
    for app_label, model_name in candidates:
        try:
            return _get_model(app_label, model_name)
        except Exception as e:
            last_err = e
    raise LookupError(
        f"تعذر العثور على الموديل من المرشحين: {candidates}. آخر خطأ: {last_err}"
    )


@lru_cache(maxsize=32)
def SchoolModel():
    return _get_model_first(("core", "School"))


@lru_cache(maxsize=32)
def UserProfileModel():
    return _get_model_first(("core", "UserProfile"))


@lru_cache(maxsize=32)
def SchoolSettingsModel():
    return _get_model_first(("schedule", "SchoolSettings"))


@lru_cache(maxsize=32)
def SchoolClassModel():
    return _get_model_first(("schedule", "SchoolClass"))


@lru_cache(maxsize=32)
def SubjectModel():
    return _get_model_first(("schedule", "Subject"))


@lru_cache(maxsize=32)
def TeacherModel():
    return _get_model_first(("schedule", "Teacher"))


@lru_cache(maxsize=32)
def DayScheduleModel():
    return _get_model_first(("schedule", "DaySchedule"))


@lru_cache(maxsize=32)
def PeriodModel():
    return _get_model_first(("schedule", "Period"))


@lru_cache(maxsize=32)
def BreakModel():
    return _get_model_first(("schedule", "Break"))


@lru_cache(maxsize=32)
def ClassLessonModel():
    return _get_model_first(("schedule", "ClassLesson"))


@lru_cache(maxsize=32)
def AnnouncementModel():
    return _get_model_first(("notices", "Announcement"))


@lru_cache(maxsize=32)
def ExcellenceModel():
    return _get_model_first(("notices", "Excellence"))


@lru_cache(maxsize=32)
def StandbyAssignmentModel():
    return _get_model_first(("standby", "StandbyAssignment"))


@lru_cache(maxsize=32)
def DisplayScreenModel():
    return _get_model_first(("core", "DisplayScreen"))


# ======================
# Helpers
# ======================

def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _join_unique_msgs(msgs: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for m in msgs:
        m = (m or "").strip()
        if m and m not in seen:
            seen.add(m)
            ordered.append(m)
    return " | ".join(ordered)


def _collect_form_errors(*forms_or_formsets) -> str:
    msgs: list[str] = []
    for obj in forms_or_formsets:
        if obj is None:
            continue

        # Form
        if hasattr(obj, "errors") and hasattr(obj, "fields"):
            if obj.errors:
                for field, errs in obj.errors.items():
                    if field == "__all__":
                        for e in errs:
                            msgs.append(str(e))
                    else:
                        label = obj.fields.get(field).label if field in obj.fields else field
                        for e in errs:
                            msgs.append(f"{label}: {e}")

        # FormSet
        if hasattr(obj, "forms") and hasattr(obj, "non_form_errors"):
            for f in getattr(obj, "forms", []):
                if getattr(f, "errors", None):
                    for field, errs in f.errors.items():
                        if field == "__all__":
                            for e in errs:
                                msgs.append(str(e))
                        else:
                            label = f.fields.get(field).label if field in f.fields else field
                            for e in errs:
                                msgs.append(f"{label}: {e}")
            for e in obj.non_form_errors():
                msgs.append(str(e))

    return _join_unique_msgs(msgs)


def _to_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(default)


def _rev_manager(obj, preferred: str, fallback: str):
    mgr = getattr(obj, preferred, None)
    if mgr is None:
        mgr = getattr(obj, fallback, None)
    return mgr


def _parse_hhmm_or_hhmmss(s: str) -> time:
    raw = (s or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    raise ValueError("صيغة الوقت غير صحيحة. استخدم HH:MM أو HH:MM:SS.")


def _get_or_create_profile(user):
    Profile = UserProfileModel()
    profile, _created = Profile.objects.get_or_create(user=user)
    return profile


def _safe_next_url(request, default_name: str = "dashboard:index") -> str:
    nxt = (request.GET.get("next") or request.POST.get("next") or "").strip()
    if not nxt:
        return reverse(default_name)
    allowed_hosts = {request.get_host()}
    try:
        allowed_hosts |= set(dj_settings.ALLOWED_HOSTS or [])
    except Exception:
        pass
    if url_has_allowed_host_and_scheme(nxt, allowed_hosts=allowed_hosts, require_https=request.is_secure()):
        return nxt
    return reverse(default_name)


def _classes_qs_from_settings(settings_obj):
    """
    بعض المشاريع تسمي علاقة الفصول: settings.school_classes
    وبعضها: settings.classes أو schoolclass_set
    نخليها مرنة حتى لا تتكسر الصفحات.
    """
    if settings_obj is None:
        return SchoolClassModel().objects.none()

    for preferred, fallback in (("school_classes", "schoolclass_set"), ("classes", "schoolclass_set")):
        mgr = _rev_manager(settings_obj, preferred, fallback)
        if mgr is not None:
            try:
                return mgr.all()
            except Exception:
                continue

    # كحل أخير: حاول عبر موديل SchoolClass مباشرة
    try:
        SchoolClass = SchoolClassModel()
        return SchoolClass.objects.filter(settings=settings_obj)
    except Exception:
        return SchoolClassModel().objects.none()


def get_active_school_or_redirect(request):
    """
    يرجّع (school, response)
    - school: مدرسة نشطة (School) أو None
    - response: HttpResponseRedirect أو None

    مهم: لا تُرجع إلى صفحة login هنا إطلاقًا حتى لا يحدث Redirect loop.
    """
    profile = _get_or_create_profile(request.user)

    try:
        schools_ids = list(profile.schools.values_list("id", flat=True))
    except Exception:
        schools_ids = []

    logger.debug(
        "active_school check: user=%s active_school_id=%s schools=%s",
        getattr(request.user, "pk", None),
        getattr(profile, "active_school_id", None),
        schools_ids,
    )

    if getattr(profile, "active_school_id", None):
        return profile.active_school, None

    schools_mgr = getattr(profile, "schools", None)
    if schools_mgr is not None:
        qs = profile.schools.order_by("id")
        if qs.exists():
            first_school = qs.first()
            profile.active_school = first_school
            profile.save(update_fields=["active_school"])
            messages.info(request, f"تم تعيين المدرسة النشطة تلقائيًا: {first_school.name}")
            return first_school, None

    # System staff (SaaS): superuser أو موظف دعم
    try:
        is_support = request.user.groups.filter(name="Support").exists()
    except Exception:
        is_support = False

    if getattr(request.user, "is_superuser", False) or is_support:
        messages.info(request, "لا توجد مدرسة مرتبطة بحسابك — تم تحويلك للوحة إدارة النظام.")
        return None, redirect("dashboard:system_admin_dashboard")

    messages.error(request, "حسابك غير مرتبط بأي مدرسة. يرجى التواصل مع الإدارة.")
    return None, redirect("dashboard:select_school")


# ======================
# مصادقة ولوحة المدير
# ======================

def login_view(request):
    if request.user.is_authenticated:
        try:
            is_support = request.user.groups.filter(name="Support").exists()
        except Exception:
            is_support = False

        if getattr(request.user, "is_superuser", False) or is_support:
            return redirect("dashboard:system_admin_dashboard")
        _school, resp = get_active_school_or_redirect(request)
        return resp or redirect("dashboard:index")

    if request.method == "POST":
        u = (request.POST.get("username") or "").strip()
        p = request.POST.get("password") or ""
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            try:
                is_support = user.groups.filter(name="Support").exists()
            except Exception:
                is_support = False

            if getattr(user, "is_superuser", False) or is_support:
                return redirect(_safe_next_url(request, default_name="dashboard:system_admin_dashboard"))
            _school, resp = get_active_school_or_redirect(request)
            return resp or redirect(_safe_next_url(request, default_name="dashboard:index"))

        messages.error(request, "بيانات الدخول غير صحيحة.")

    return render(request, "dashboard/login.html")


def demo_login(request):
    School = SchoolModel()
    DEMO_ID = "demo_user"
    DEMO_SCHOOL_SLUG = "demo-school"

    demo_school, _ = School.objects.get_or_create(
        slug=DEMO_SCHOOL_SLUG,
        defaults={"name": "مدرسة تجريبية", "is_active": True},
    )

    lookup = {}
    defaults: dict[str, Any] = {"is_active": True}
    if _model_has_field(UserModel, "username"):
        lookup["username"] = DEMO_ID
        defaults.update({"first_name": "حساب", "last_name": "تجريبي", "email": "demo@example.com"})
    elif _model_has_field(UserModel, "phone"):
        lookup["phone"] = "0500000000"
        defaults.update({"name": "حساب تجريبي"})
    else:
        lookup["email"] = "demo@example.com"
        defaults.update({"first_name": "Demo", "last_name": "User"})

    demo_user, created = UserModel.objects.get_or_create(**lookup, defaults=defaults)
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
    next_url = _safe_next_url(request, default_name="dashboard:index")
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "تم تغيير كلمة المرور بنجاح!")
            return redirect(next_url)
        messages.error(request, "الرجاء تصحيح الأخطاء أدناه.")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "dashboard/change_password.html", {"form": form, "next": next_url})


@manager_required
def index(request):
    Announcement = AnnouncementModel()
    Excellence = ExcellenceModel()
    StandbyAssignment = StandbyAssignmentModel()
    SchoolSettings = SchoolSettingsModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    if school is None:
        return render(request, "dashboard/no_school.html")

    today = timezone.localdate()
    stats = {
        "ann_count": Announcement.objects.filter(school=school).count(),
        "exc_count": Excellence.objects.filter(school=school).count(),
        "standby_today": StandbyAssignment.objects.filter(school=school, date=today).count(),
    }

    settings_obj = SchoolSettings.objects.filter(school=school).first()

    SubModel = _get_subscription_model()
    subscription = None
    if SubModel is not None:
        subscription = SubModel.objects.filter(school=school).order_by("-starts_at", "-id").first()

    return render(
        request,
        "dashboard/index.html",
        {"stats": stats, "settings": settings_obj, "subscription": subscription},
    )


@login_required
def select_school(request):
    profile = _get_or_create_profile(request.user)

    if getattr(request.user, "is_superuser", False):
        return redirect("dashboard:system_admin_dashboard")

    schools_qs = getattr(profile, "schools", None)
    if schools_qs is None:
        return render(request, "dashboard/no_school.html")

    schools = profile.schools.order_by("name", "id")
    if not schools.exists():
        return render(request, "dashboard/no_school.html")

    if request.method == "POST":
        sid = (request.POST.get("school_id") or "").strip()
        try:
            school = profile.schools.get(pk=int(sid))
        except Exception:
            messages.error(request, "المدرسة غير موجودة أو ليست ضمن صلاحياتك.")
            return redirect("dashboard:select_school")

        profile.active_school = school
        profile.save(update_fields=["active_school"])
        messages.success(request, f"تم اختيار المدرسة النشطة: {school.name}")

        return redirect(_safe_next_url(request, default_name="dashboard:index"))

    return render(
        request,
        "dashboard/select_school.html",
        {"schools": schools, "active_school_id": getattr(profile, "active_school_id", None)},
    )


# ======================
# إعدادات المدرسة
# ======================

@manager_required
def school_settings(request):
    SchoolSettings = SchoolSettingsModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    obj, _created = SchoolSettings.objects.get_or_create(
        school=school,
        defaults={"name": school.name},
    )

    # Preview: use latest active screen short_code if exists
    preview_url = None
    try:
        from core.models import DisplayScreen  # local import

        scr = (
            DisplayScreen.objects
            .filter(school=school, is_active=True)
            .exclude(short_code__isnull=True)
            .exclude(short_code__exact="")
            .order_by("-id")
            .first()
        )
        if scr:
            preview_url = f"/s/{scr.short_code}/"
    except Exception:
        preview_url = None

    if request.method == "POST":
        form = SchoolSettingsForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ إعدادات المدرسة.")
            return redirect("dashboard:settings")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSettingsForm(instance=obj)

    return render(request, "dashboard/settings.html", {"form": form, "display_preview_url": preview_url})


# ======================
# إدارة أيام الجدول
# ======================

@manager_required
def days_list(request):
    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    existing = set(
        DaySchedule.objects.filter(settings=settings_obj, weekday__in=SCHOOL_WEEKDAY_IDS)
        .values_list("weekday", flat=True)
    )

    for w in SCHOOL_WEEKDAY_IDS:
        if w not in existing:
            DaySchedule.objects.create(
                settings=settings_obj,
                weekday=w,
                periods_count=7 if w in (0, 1) else 6,
                is_active=True,
            )

    days = list(
        DaySchedule.objects.filter(settings=settings_obj, weekday__in=SCHOOL_WEEKDAY_IDS)
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
        total_periods += d.periods_count or 0

    avg_periods = total_periods / len(days) if days else 0
    max_periods_day = max(days, key=lambda d: d.periods_count) if days else None
    min_periods_day = min(days, key=lambda d: d.periods_count) if days else None

    return render(
        request,
        "dashboard/days_list.html",
        {
            "days": days,
            "total_periods": total_periods,
            "avg_periods": avg_periods,
            "max_periods_day": max_periods_day,
            "min_periods_day": min_periods_day,
        },
    )


@manager_required
@transaction.atomic
def day_edit(request, weekday: int):
    if weekday not in SCHOOL_WEEKDAY_IDS:
        messages.error(request, "اليوم غير موجود في قائمة الأيام الدراسية.")
        return redirect("dashboard:days_list")

    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

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

        if form.is_valid() and p_formset.is_valid() and b_formset.is_valid():
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
        {"day": day, "form": form, "p_formset": p_formset, "b_formset": b_formset},
    )


@manager_required
@transaction.atomic
@require_POST
def day_autofill(request, weekday: int):
    if weekday not in SCHOOL_WEEKDAY_IDS:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسي.")
        return redirect("dashboard:days_list")

    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    try:
        # Check if user wants to update period count along with autofill
        new_count = _to_int(request.POST.get("target_periods_count"), 0)
        if new_count > 0:
            day.periods_count = new_count
            day.save()

        start_time_str = request.POST.get("start_time", "07:00:00")
        period_minutes = _to_int(request.POST.get("period_minutes"), 45)
        period_seconds = _to_int(request.POST.get("period_seconds"), 0)
        gap_minutes = _to_int(request.POST.get("gap_minutes"), 0)
        gap_seconds = _to_int(request.POST.get("gap_seconds"), 0)
        break_after = _to_int(request.POST.get("break_after"), 0)
        break_minutes = _to_int(request.POST.get("break_minutes"), 0)
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
        if periods_mgr is None or breaks_mgr is None:
            raise ValueError("تعذر الوصول لعلاقات الحصص/الفسح (تحقق من related_name).")

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
            periods_mgr.create(index=i, starts_at=start_period.time(), ends_at=end_period.time())
            cursor = end_period

            if break_minutes_final > 0 and break_after == i:
                breaks_mgr.create(label="فسحة", starts_at=cursor.time(), duration_min=break_minutes_final)
                cursor += timedelta(minutes=break_minutes_final)

            cursor += gap

        messages.success(request, "تمت التعبئة التلقائية للجدول.")
        return redirect("dashboard:day_edit", weekday=weekday)

    except Exception as e:
        logger.exception("day_autofill failed")
        messages.error(request, f"تعذّر تنفيذ التعبئة: {e}")
        return redirect("dashboard:day_edit", weekday=weekday)


@manager_required
@require_POST
def day_toggle(request, weekday: int):
    if weekday not in SCHOOL_WEEKDAY_IDS:
        messages.error(request, "اليوم غير صالح.")
        return redirect("dashboard:days_list")

    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day, _ = DaySchedule.objects.get_or_create(settings=settings_obj, weekday=weekday)
    day.is_active = not bool(getattr(day, "is_active", True))
    day.save(update_fields=["is_active"])

    status = "تفعيل" if day.is_active else "تعطيل"
    messages.success(request, f"تم {status} يوم {WEEKDAY_MAP.get(weekday, str(weekday))}.")
    return redirect("dashboard:days_list")


# ======================
# التنبيهات وبطاقات التميز
# ======================

@manager_required
def ann_list(request):
    Announcement = AnnouncementModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    qs = Announcement.objects.filter(school=school).order_by("-starts_at", "-id")
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "dashboard/ann_list.html", {"page": page})


@manager_required
def ann_create(request):
    Announcement = AnnouncementModel()
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
    Announcement = AnnouncementModel()
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
@require_POST
def ann_delete(request, pk: int):
    Announcement = AnnouncementModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(Announcement, pk=pk, school=school)
    obj.delete()
    messages.success(request, "تم حذف التنبيه.")
    return redirect("dashboard:ann_list")


@manager_required
def exc_list(request):
    Excellence = ExcellenceModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    qs = Excellence.objects.filter(school=school).order_by("priority", "-start_at", "-id")

    now = timezone.now()
    active_count = Excellence.objects.filter(
        Q(school=school) & Q(start_at__lte=now) & (Q(end_at__isnull=True) | Q(end_at__gt=now))
    ).count()
    expired_count = Excellence.objects.filter(school=school, end_at__lte=now).count()
    max_p = Excellence.objects.filter(school=school).aggregate(m=Max("priority"))["m"] or 0

    page = Paginator(qs, 12).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/exc_list.html",
        {"page": page, "active_count": active_count, "expired_count": expired_count, "max_priority": max_p},
    )


@manager_required
def exc_create(request):
    Excellence = ExcellenceModel()
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
    Excellence = ExcellenceModel()
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
@require_POST
def exc_delete(request, pk: int):
    Excellence = ExcellenceModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    obj.delete()
    messages.success(request, "تم حذف البطاقة.")
    return redirect("dashboard:exc_list")


# ======================
# حصص الانتظار
# ======================

@manager_required
def standby_list(request):
    StandbyAssignment = StandbyAssignmentModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    qs = StandbyAssignment.objects.filter(school=school).order_by("-date", "period_index", "-id")

    today = timezone.localdate()
    today_count = StandbyAssignment.objects.filter(school=school, date=today).count()
    teachers_count = StandbyAssignment.objects.filter(school=school).values("teacher_name").distinct().count()
    classes_count = StandbyAssignment.objects.filter(school=school).values("class_name").distinct().count()

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    return render(
        request,
        "dashboard/standby_list.html",
        {"page": page, "today_count": today_count, "teachers_count": teachers_count, "classes_count": classes_count},
    )


@manager_required
def standby_create(request):
    StandbyAssignment = StandbyAssignmentModel()
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
@require_POST
def standby_delete(request, pk: int):
    StandbyAssignment = StandbyAssignmentModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(StandbyAssignment, pk=pk, school=school)
    obj.delete()
    messages.success(request, "تم الحذف.")
    return redirect("dashboard:standby_list")


@manager_required
def standby_import(request):
    StandbyAssignment = StandbyAssignmentModel()
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
        new_items = []

        skipped = 0
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

                new_items.append(
                    StandbyAssignment(
                        school=school,
                        date=parsed_date,
                        period_index=period_index,
                        class_name=(row.get("class_name") or "").strip(),
                        teacher_name=(row.get("teacher_name") or "").strip(),
                        notes=(row.get("notes") or "").strip(),
                    )
                )
            except Exception:
                skipped += 1
                continue

        count = 0
        if new_items:
            StandbyAssignment.objects.bulk_create(new_items, batch_size=500)
            count = len(new_items)

        if skipped:
            messages.warning(request, f"تم استيراد {count} سجل، وتجاوز {skipped} صف بسبب بيانات غير صحيحة.")
        else:
            messages.success(request, f"تم استيراد {count} سجل.")
        return redirect("dashboard:standby_list")

    return render(request, "dashboard/standby_import.html")


# ======================
# شاشات العرض
# ======================

def _get_school_active_subscriptions_qs(school):
    """يرجع QuerySet للاشتراكات السارية (قد تكون أكثر من اشتراك)."""
    SubModel = _get_subscription_model()
    if SubModel is None:
        return None

    today = timezone.localdate()
    qs = SubModel.objects.all()

    # school filter
    try:
        SubModel._meta.get_field("school")
        qs = qs.filter(school=school)
    except Exception:
        try:
            SubModel._meta.get_field("school_id")
            qs = qs.filter(school_id=getattr(school, "id", school))
        except Exception:
            return None

    # active status
    try:
        SubModel._meta.get_field("status")
        qs = qs.filter(status="active")
    except Exception:
        try:
            SubModel._meta.get_field("is_active")
            qs = qs.filter(is_active=True)
        except Exception:
            pass

    # start date
    for f in ("starts_at", "start_date"):
        try:
            SubModel._meta.get_field(f)
            qs = qs.filter(**{f"{f}__lte": today})
            break
        except Exception:
            continue

    # end date
    for f in ("ends_at", "end_date"):
        try:
            SubModel._meta.get_field(f)
            qs = qs.filter(Q(**{f"{f}__isnull": True}) | Q(**{f"{f}__gte": today}))
            break
        except Exception:
            continue

    # select plan if possible
    try:
        SubModel._meta.get_field("plan")
        # نستخدم defer لتجنب الحقول التي قد لا تكون موجودة في قاعدة البيانات (مثل duration_days في بعض البيئات)
        qs = qs.select_related("plan").defer("plan__duration_days")
    except Exception:
        pass

    return qs


def _get_school_active_subscription(school):
    """يرجع اشتراك المدرسة الساري (إن وجد) بشكل مرن بين subscriptions و legacy."""
    qs = _get_school_active_subscriptions_qs(school)
    if qs is None:
        return None
    # ملاحظة: قد يوجد أكثر من اشتراك نشط. سنختار "أفضل" اشتراك (الأعلى في max_screens أو غير محدود).
    subs = list(qs)
    if not subs:
        return None

    def _key(sub):
        plan = getattr(sub, "plan", None)
        ms = getattr(plan, "max_screens", None) if plan else None
        # None = غير محدود => أعلى
        return (1 if ms is None else 0, int(ms or 0))

    subs.sort(key=_key, reverse=True)
    return subs[0]


def _get_school_max_screens_limit(school) -> int | None:
    """يرجع الحد الأقصى للشاشات حسب خطة الاشتراك. None = غير محدود.

    إذا كانت subscriptions.utils.school_effective_max_screens متاحة، سيتم استخدامها
    لتضمين زيادات الشاشات (Add-ons) ضمن الحد.
    """
    try:
        from subscriptions.utils import school_effective_max_screens  # local import لتجنب دورات الاستيراد

        return school_effective_max_screens(getattr(school, "id", None))
    except Exception:
        # fallback للمنطق القديم (بدون Add-ons)
        pass

    qs = _get_school_active_subscriptions_qs(school)
    if qs is None:
        return 0
    subs = list(qs)
    if not subs:
        return 0

    # لو أي اشتراك نشط غير محدود => غير محدود
    for sub in subs:
        plan = getattr(sub, "plan", None)
        if plan is not None and getattr(plan, "max_screens", None) is None:
            return None

    # اختر الحد الأعلى بين الاشتراكات النشطة
    best = 0
    for sub in subs:
        plan = getattr(sub, "plan", None)
        ms = getattr(plan, "max_screens", None) if plan else None
        try:
            ms_i = int(ms or 0)
        except Exception:
            ms_i = 0
        if ms_i > best:
            best = ms_i
    return best


def _get_school_effective_plan_label(school) -> str | None:
    """اسم الخطة المستخدمة لعرض المعلومات في الواجهة (أفضل اشتراك)."""
    sub = _get_school_active_subscription(school)
    if not sub:
        return None
    plan = getattr(sub, "plan", None)
    return getattr(plan, "name", None) if plan else None

@manager_required
def screen_list(request):
    DisplayScreen = DisplayScreenModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    try:
        from core.screen_limits import enforce_school_screen_limit
        enforce_school_screen_limit(int(getattr(school, "id", 0) or 0))
    except Exception:
        pass

    # عدد الشاشات التي تم إيقافها تلقائيًا بسبب تجاوز الحد
    auto_disabled_count = 0
    try:
        if _model_has_field(DisplayScreen, "auto_disabled_by_limit"):
            auto_disabled_count = DisplayScreen.objects.filter(
                school=school,
                auto_disabled_by_limit=True,
            ).count()
    except Exception:
        auto_disabled_count = 0

    qs = DisplayScreen.objects.filter(school=school).order_by("-created_at", "-id")
    current_count = qs.count()
    max_screens = _get_school_max_screens_limit(school)
    plan_name = _get_school_effective_plan_label(school)

    if max_screens is None:
        screens_remaining = None
    else:
        try:
            screens_remaining = max(int(max_screens) - int(current_count), 0)
        except Exception:
            screens_remaining = 0

    if max_screens is None:
        can_create_screen = True
        show_screen_limit_message = False
        screen_limit_message = None
    else:
        can_create_screen = current_count < int(max_screens)
        show_screen_limit_message = not can_create_screen
        if max_screens <= 0:
            screen_limit_message = "لا يمكن إضافة شاشات لهذه المدرسة (لا يوجد اشتراك نشط)."
        else:
            screen_limit_message = f"لا يمكن إضافة أكثر من {int(max_screens)} شاشة لهذه المدرسة"

    return render(
        request,
        "dashboard/screen_list.html",
        {
            "screens": qs,
            "can_create_screen": can_create_screen,
            "show_screen_limit_message": show_screen_limit_message,
            "screen_limit": None if max_screens is None else int(max_screens),
            "screen_limit_message": screen_limit_message,
            "screens_count": current_count,
            "plan_name": plan_name,
            "screens_remaining": screens_remaining,
            "auto_disabled_count": auto_disabled_count,
        },
    )


@manager_required
def screen_create(request):
    DisplayScreen = DisplayScreenModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    current_count = DisplayScreen.objects.filter(school=school).count()
    max_screens = _get_school_max_screens_limit(school)
    if (max_screens is not None) and (current_count >= int(max_screens)):
        if max_screens <= 0:
            messages.warning(request, "لا يمكن إنشاء شاشة بدون اشتراك نشط.")
        else:
            messages.warning(request, f"لا يمكن إنشاء أكثر من {int(max_screens)} شاشة لهذه المدرسة.")
        return redirect("dashboard:screen_list")

    if request.method == "POST":
        form = DisplayScreenForm(request.POST)
        if form.is_valid():
            screen = form.save(commit=False)
            screen.school = school
            screen.save()
            messages.success(
                request,
                "تم إضافة شاشة جديدة.\n\n"
                "تنبيه مهم:\n"
                "- سيتم حفظ الشاشة على أول تلفاز/متصفح يتم فتح الرابط عليه، ولا يمكن فتحها على جهاز آخر إلا بعد فصل الجهاز من لوحة التحكم.\n"
                "- المحتوى موحّد وثابت في جميع الشاشات.",
            )
            return redirect("dashboard:screen_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = DisplayScreenForm()

    return render(request, "dashboard/screen_form.html", {"form": form, "title": "إضافة شاشة"})


@manager_required
@require_POST
def screen_delete(request, pk: int):
    DisplayScreen = DisplayScreenModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response
    obj = get_object_or_404(DisplayScreen, pk=pk, school=school)
    obj.delete()
    messages.success(request, "تم حذف الشاشة.")
    return redirect("dashboard:screen_list")


@manager_required
@require_POST
def screen_unbind_device(request, pk: int):
    DisplayScreen = DisplayScreenModel()
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    obj = get_object_or_404(DisplayScreen, pk=pk, school=school)

    # حقول الربط قد لا تكون موجودة في بيئات قديمة
    try:
        DisplayScreen._meta.get_field("bound_device_id")
        DisplayScreen._meta.get_field("bound_at")
    except Exception:
        messages.error(request, "ميزة ربط الأجهزة غير متاحة حالياً.")
        return redirect("dashboard:screen_list")

    DisplayScreen.objects.filter(pk=obj.pk).update(bound_device_id=None, bound_at=None)

    # ✅ مهم: امسح كاش الربط حتى لا يبقى bound_device_id القديم (24h) ويمنع الربط بجهاز جديد
    try:
        from django.core.cache import cache
        import hashlib

        token_value = (getattr(obj, "token", None) or getattr(obj, "api_token", None) or "").strip()
        if token_value:
            token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
            cache.delete(f"display:token_map:{token_hash}")
    except Exception:
        pass

    messages.success(request, "تم فصل الجهاز. افتح الرابط على التلفاز الجديد ليتم ربطه تلقائياً.")
    return redirect("dashboard:screen_list")


# ======================
# أدوات إضافية على الأيام
# ======================

@manager_required
@transaction.atomic
@require_POST
def day_clear(request, weekday: int):
    if weekday not in SCHOOL_WEEKDAY_IDS:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسية.")
        return redirect("dashboard:days_list")

    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    periods_mgr = _rev_manager(day, "periods", "period_set")
    breaks_mgr = _rev_manager(day, "breaks", "break_set")

    if periods_mgr is not None:
        periods_mgr.all().delete()
    if breaks_mgr is not None:
        breaks_mgr.all().delete()

    messages.success(request, "تم مسح جميع الحصص والفسح لهذا اليوم.")
    return redirect("dashboard:day_edit", weekday=weekday)


@manager_required
@transaction.atomic
@require_POST
def day_reindex(request, weekday: int):
    if weekday not in SCHOOL_WEEKDAY_IDS:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسية.")
        return redirect("dashboard:days_list")

    SchoolSettings = SchoolSettingsModel()
    DaySchedule = DayScheduleModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    periods_mgr = _rev_manager(day, "periods", "period_set")
    if periods_mgr is None:
        messages.error(request, "تعذر الوصول للحصص (تحقق من related_name).")
        return redirect("dashboard:day_edit", weekday=weekday)

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
    SchoolSettings = SchoolSettingsModel()
    ClassLesson = ClassLessonModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    lessons = ClassLesson.objects.none()
    if settings_obj:
        lessons = (
            ClassLesson.objects.filter(settings=settings_obj)
            .select_related("school_class", "subject", "teacher")
            .order_by("weekday", "period_index", "school_class__name")
        )

    search = (request.GET.get("search") or "").strip()
    day = (request.GET.get("day") or "").strip()

    if search:
        lessons = lessons.filter(
            Q(school_class__name__icontains=search)
            | Q(subject__name__icontains=search)
            | Q(teacher__name__icontains=search)
        )

    if day.isdigit():
        lessons = lessons.filter(weekday=int(day))

    return render(request, "dashboard/lessons_list.html", {"lessons": lessons})


@manager_required
def lesson_create(request):
    SchoolSettings = SchoolSettingsModel()
    Subject = SubjectModel()
    Teacher = TeacherModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:lessons_list")

    form = LessonForm(request.POST or None)

    classes_qs = _classes_qs_from_settings(settings_obj).order_by("name")
    form.fields["school_class"].queryset = classes_qs
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
    SchoolSettings = SchoolSettingsModel()
    ClassLesson = ClassLessonModel()
    Subject = SubjectModel()
    Teacher = TeacherModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:lessons_list")

    obj = get_object_or_404(ClassLesson, pk=pk, settings=settings_obj)

    form = LessonForm(request.POST or None, instance=obj)

    classes_qs = _classes_qs_from_settings(settings_obj).order_by("name")
    form.fields["school_class"].queryset = classes_qs
    form.fields["subject"].queryset = Subject.objects.filter(school=school).order_by("name")
    form.fields["teacher"].queryset = Teacher.objects.filter(school=school).order_by("name")

    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, "تم تعديل الحصة بنجاح.")
            return redirect("dashboard:lessons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")

    return render(request, "dashboard/lesson_form.html", {"form": form, "title": "تعديل حصة"})


@manager_required
@require_POST
def lesson_delete(request, pk: int):
    SchoolSettings = SchoolSettingsModel()
    ClassLesson = ClassLessonModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:lessons_list")

    obj = get_object_or_404(ClassLesson, pk=pk, settings=settings_obj)
    obj.delete()
    messages.success(request, "تم حذف الحصة.")
    return redirect("dashboard:lessons_list")


# ======================
# بيانات المدرسة (فصول/مواد/معلمين)
# ======================

@manager_required
def school_data(request):
    SchoolSettings = SchoolSettingsModel()
    Subject = SubjectModel()
    Teacher = TeacherModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()

    classes = _classes_qs_from_settings(settings_obj).order_by("name")
    subjects = Subject.objects.filter(school=school).order_by("name")
    teachers = Teacher.objects.filter(school=school).order_by("name")

    return render(
        request,
        "dashboard/school_data.html",
        {"classes": classes, "subjects": subjects, "teachers": teachers},
    )


@manager_required
@require_POST
def add_class(request):
    SchoolSettings = SchoolSettingsModel()
    SchoolClass = SchoolClassModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "فضلاً أدخل اسم الفصل.")
        return redirect("dashboard:school_data")

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.error(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    SchoolClass.objects.get_or_create(settings=settings_obj, name=name)
    messages.success(request, "تمت إضافة الفصل.")
    return redirect("dashboard:school_data")


@manager_required
@require_POST
def add_subject(request):
    Subject = SubjectModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "فضلاً أدخل اسم المادة.")
        return redirect("dashboard:school_data")

    Subject.objects.get_or_create(school=school, name=name)
    messages.success(request, "تمت إضافة المادة.")
    return redirect("dashboard:school_data")


@manager_required
@require_POST
def add_teacher(request):
    Teacher = TeacherModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "فضلاً أدخل اسم المعلم/ـة.")
        return redirect("dashboard:school_data")

    Teacher.objects.get_or_create(school=school, name=name)
    messages.success(request, "تمت إضافة المعلم/ـة.")
    return redirect("dashboard:school_data")


@manager_required
@require_POST
def delete_class(request, pk: int):
    SchoolClass = SchoolClassModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    deleted, _ = SchoolClass.objects.filter(pk=pk, settings__school=school).delete()
    if deleted:
        messages.success(request, "تم حذف الفصل.")
    else:
        messages.error(request, "الفصل غير موجود.")
    return redirect("dashboard:school_data")


@manager_required
@require_POST
def delete_subject(request, pk: int):
    Subject = SubjectModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    deleted, _ = Subject.objects.filter(pk=pk, school=school).delete()
    if deleted:
        messages.success(request, "تم حذف المادة.")
    else:
        messages.error(request, "المادة غير موجودة.")
    return redirect("dashboard:school_data")


@manager_required
@require_POST
def delete_teacher(request, pk: int):
    Teacher = TeacherModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    deleted, _ = Teacher.objects.filter(pk=pk, school=school).delete()
    if deleted:
        messages.success(request, "تم حذف المعلم/ـة.")
    else:
        messages.error(request, "المعلم/ـة غير موجود.")
    return redirect("dashboard:school_data")


# ======================
# جداول الحصص (يوم/أسبوع/تصدير)
# ======================

@manager_required
def timetable_day_view(request):
    SchoolSettings = SchoolSettingsModel()
    Period = PeriodModel()
    Subject = SubjectModel()
    Teacher = TeacherModel()
    ClassLesson = ClassLessonModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    weekdays_choices = list(SCHOOL_WEEK)
    default_weekday = weekdays_choices[0][0] if weekdays_choices else 0

    weekday_param = request.GET.get("weekday") if request.method == "GET" else request.POST.get("weekday")
    class_param = request.GET.get("class_id") if request.method == "GET" else request.POST.get("class_id")

    try:
        weekday = int(weekday_param) if weekday_param not in (None, "") else int(default_weekday)
    except (TypeError, ValueError):
        weekday = int(default_weekday)

    classes_qs = _classes_qs_from_settings(settings_obj).order_by("name")

    selected_class = None
    if classes_qs.exists():
        try:
            if class_param not in (None, ""):
                selected_class = classes_qs.get(pk=int(class_param))
            else:
                selected_class = classes_qs.first()
        except (ValueError, classes_qs.model.DoesNotExist):
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

    lessons_map: dict[int, object] = {l.period_index: l for l in existing_lessons_qs}

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
                        subject_obj = subjects_by_id.get(int(subject_raw))
                    except (TypeError, ValueError):
                        subject_obj = None

                if teacher_raw:
                    try:
                        teacher_obj = teachers_by_id.get(int(teacher_raw))
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

    return render(
        request,
        "dashboard/timetable_day.html",
        {
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
        },
    )


@manager_required
def timetable_week_view(request):
    SchoolSettings = SchoolSettingsModel()
    Period = PeriodModel()
    ClassLesson = ClassLessonModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if settings_obj is None:
        messages.error(request, "يجب أولاً إعداد إعدادات المدرسة والجدول الزمني.")
        return redirect("dashboard:settings")

    class_param = request.GET.get("class_id")
    classes_qs = _classes_qs_from_settings(settings_obj).order_by("name")

    if not classes_qs.exists():
        messages.error(request, "لا توجد فصول مسجلة لهذه المدرسة.")
        return redirect("dashboard:timetable_day")

    try:
        selected_class = classes_qs.get(pk=int(class_param)) if class_param else classes_qs.first()
    except (ValueError, classes_qs.model.DoesNotExist):
        selected_class = classes_qs.first()

    all_periods_qs = Period.objects.filter(
        day__settings=settings_obj, day__weekday__in=SCHOOL_WEEKDAY_IDS
    ).order_by("day__weekday", "index")

    periods_by_weekday: dict[int, list] = {}
    for p in all_periods_qs:
        periods_by_weekday.setdefault(p.day.weekday, []).append(p)

    all_lessons_qs = ClassLesson.objects.filter(
        settings=settings_obj,
        school_class=selected_class,
        weekday__in=SCHOOL_WEEKDAY_IDS,
    ).select_related("subject", "teacher")

    lessons_by_weekday_period: dict[int, dict[int, object]] = {}
    for lesson in all_lessons_qs:
        lessons_by_weekday_period.setdefault(lesson.weekday, {})[lesson.period_index] = lesson

    days_data = []
    for weekday, label in SCHOOL_WEEK:
        rows = []
        for period in periods_by_weekday.get(weekday, []):
            lesson = lessons_by_weekday_period.get(weekday, {}).get(period.index)
            rows.append(
                {
                    "period": period,
                    "lesson": lesson,
                    "subject_name": lesson.subject.name if lesson and lesson.subject else "",
                    "teacher_name": lesson.teacher.name if lesson and lesson.teacher else "",
                }
            )
        days_data.append({"weekday": weekday, "label": label, "rows": rows})

    return render(
        request,
        "dashboard/timetable_week.html",
        {"school": school, "settings": settings_obj, "selected_class": selected_class, "days_data": days_data},
    )


@manager_required
def timetable_export_csv(request):
    SchoolSettings = SchoolSettingsModel()
    Period = PeriodModel()
    ClassLesson = ClassLessonModel()

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

    classes_qs = _classes_qs_from_settings(settings_obj)
    try:
        school_class = classes_qs.get(pk=int(class_param))
    except (ValueError, classes_qs.model.DoesNotExist):
        messages.error(request, "الفصل المحدد غير موجود.")
        return redirect("dashboard:timetable_day")

    periods_qs = Period.objects.filter(day__settings=settings_obj).select_related("day")
    period_map: dict[tuple[int, int], object] = {(p.day.weekday, p.index): p for p in periods_qs}

    lessons = (
        ClassLesson.objects.filter(settings=settings_obj, school_class=school_class)
        .select_related("subject", "teacher")
        .order_by("weekday", "period_index")
    )

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"timetable_{school_class.name}.csv"
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("\ufeff")

    writer = csv.writer(resp)
    writer.writerow(["اليوم", "رقم الحصة", "وقت البداية", "وقت النهاية", "المادة", "المعلم/ـة"])

    for lesson in lessons:
        period = period_map.get((lesson.weekday, lesson.period_index))
        day_label = WEEKDAY_MAP.get(lesson.weekday, str(lesson.weekday))
        start_str = period.starts_at.strftime("%H:%M") if period and period.starts_at else ""
        end_str = period.ends_at.strftime("%H:%M") if period and period.ends_at else ""
        subject_name = lesson.subject.name if lesson.subject else ""
        teacher_name = lesson.teacher.name if lesson.teacher else ""
        writer.writerow([day_label, lesson.period_index, start_str, end_str, subject_name, teacher_name])

    return resp


# =========================
#  لوحة إدارة النظام (SaaS)
# =========================

def superuser_required(view_func):
    return user_passes_test(lambda u: u.is_superuser, login_url="dashboard:login")(view_func)


def system_staff_required(view_func):
    """سماح لمدير النظام أو موظف الدعم (Group: Support)."""
    def _ok(u):
        if getattr(u, "is_superuser", False):
            return True
        try:
            return u.is_authenticated and u.groups.filter(name="Support").exists()
        except Exception:
            return False

    return user_passes_test(_ok, login_url="dashboard:login")(view_func)


def _admin_school_form_class():
    School = SchoolModel()

    class AdminSchoolForm(forms.ModelForm):
        class Meta:
            model = School

            fields = ["name", "slug", "school_type", "is_active"]

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if "school_type" in self.fields:
                self.fields["school_type"].required = True
                # خيار توضيحي بدل "---------"
                choices = list(self.fields["school_type"].choices)
                if choices and choices[0][0] in ("", None):
                    choices[0] = ("", "اختر نوع المدرسة")
                else:
                    choices = [("", "اختر نوع المدرسة")] + choices
                self.fields["school_type"].choices = choices

    return AdminSchoolForm


@login_required
def switch_school(request, school_id):
    profile = _get_or_create_profile(request.user)
    try:
        school = profile.schools.get(pk=school_id)
    except Exception:
        messages.error(request, "المدرسة غير موجودة أو ليس لديك صلاحية الوصول إليها.")
        return redirect("dashboard:index")

    profile.active_school = school
    profile.save(update_fields=["active_school"])
    messages.success(request, f"تم التبديل إلى مدرسة: {school.name}")
    return redirect(_safe_next_url(request, default_name="dashboard:index"))


@system_staff_required
def system_admin_dashboard(request):
    School = SchoolModel()

    school_count = School.objects.count()
    user_count = UserModel.objects.count()

    SubModel = _get_subscription_model()
    subs_count = SubModel.objects.count() if SubModel is not None else 0

    today = timezone.localdate()
    active_subs = 0
    revenue = 0

    if SubModel is not None:
        active_qs = SubModel.objects.filter(status="active").filter(
            Q(ends_at__isnull=True) | Q(ends_at__gte=today)
        )
        active_subs = active_qs.count()
        revenue = active_qs.aggregate(total=Sum("plan__price"))["total"] or 0

    Req = _get_subscription_request_model()
    open_requests = 0
    if Req is not None:
        try:
            open_requests = Req.objects.filter(status__in=["submitted", "under_review"]).count()
        except Exception:
            open_requests = 0

    return render(
        request,
        "admin/dashboard.html",
        {
            "schools_count": school_count,
            "users_count": user_count,
            "subs_count": subs_count,
            "active_subs": active_subs,
            "subscriptions_count": active_subs,
            "revenue": revenue,
            "open_subscription_requests": open_requests,
        },
    )


@system_staff_required
def system_schools_list(request):
    School = SchoolModel()
    DisplayScreen = DisplayScreenModel()

    q = (request.GET.get("q") or "").strip()
    schools = School.objects.all().order_by("-created_at", "-id")

    if q:
        schools = schools.filter(Q(name__icontains=q) | Q(slug__icontains=q))

    # attach live stats
    try:
        schools = schools.select_related("schedule_settings")
    except Exception:
        pass

    active_window_seconds = 120
    active_since = timezone.now() - timedelta(seconds=active_window_seconds)
    screens_qs = DisplayScreen.objects.all()

    if _model_has_field(DisplayScreen, "is_active"):
        screens_qs = screens_qs.filter(is_active=True)
    if _model_has_field(DisplayScreen, "last_seen_at"):
        screens_qs = screens_qs.filter(last_seen_at__gte=active_since)

    active_counts = {
        row["school_id"]: row["c"]
        for row in screens_qs.values("school_id").annotate(c=Count("id"))
        if row.get("school_id")
    }

    schools_list = list(schools)
    for s in schools_list:
        setattr(s, "active_screens_now", int(active_counts.get(s.id, 0) or 0))
        settings_obj = getattr(s, "schedule_settings", None)
        setattr(s, "refresh_interval_sec", getattr(settings_obj, "refresh_interval_sec", None))

    return render(
        request,
        "admin/schools_list.html",
        {
            "schools": schools_list,
            "q": q,
            "active_window_seconds": active_window_seconds,
        },
    )


@system_staff_required
def system_school_create(request):
    FormCls = _admin_school_form_class()

    if request.method == "POST":
        form = FormCls(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "تمت إضافة المدرسة بنجاح.")
            return redirect("dashboard:system_schools_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = FormCls()

    return render(request, "admin/school_form.html", {"form": form, "title": "إضافة مدرسة"})


@system_staff_required
def system_school_edit(request, pk: int):
    School = SchoolModel()
    FormCls = _admin_school_form_class()

    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        form = FormCls(request.POST, request.FILES, instance=school)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات المدرسة.")
            return redirect("dashboard:system_schools_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = FormCls(instance=school)

    return render(request, "admin/school_form.html", {"form": form, "title": "تعديل مدرسة", "edit": True})


@superuser_required
def system_school_delete(request, pk: int):
    School = SchoolModel()
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        school.delete()
        messages.warning(request, f"تم حذف المدرسة: {school.name}")
        return redirect("dashboard:system_schools_list")
    return render(request, "admin/school_confirm_delete.html", {"school": school})


@system_staff_required
def system_users_list(request):
    q = (request.GET.get("q") or "").strip()

    qs = UserModel.objects.all().order_by("-id")

    try:
        qs = qs.select_related("profile", "profile__active_school").prefetch_related("profile__schools")
    except FieldError:
        try:
            qs = qs.select_related("profile")
        except FieldError:
            pass

    if q:
        filters = Q()
        for key in ("username", "email", "first_name", "last_name"):
            try:
                UserModel._meta.get_field(key)
                filters |= Q(**{f"{key}__icontains": q})
            except Exception:
                continue

        try:
            filters |= Q(profile__active_school__name__icontains=q) | Q(profile__schools__name__icontains=q)
        except Exception:
            pass

        qs = qs.filter(filters).distinct()

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    return render(request, "admin/users_list.html", {"page_obj": page_obj, "q": q})


@system_staff_required
def system_employees_list(request):
    """قائمة موظفي النظام (Superuser / Support group)."""
    q = (request.GET.get("q") or "").strip()

    qs = (
        UserModel.objects.filter(
            Q(is_staff=True) | Q(is_superuser=True) | Q(groups__name="Support")
        )
        .distinct()
        .order_by("-id")
    )

    try:
        qs = qs.prefetch_related("groups")
    except Exception:
        pass

    if q:
        filters = Q()
        for key in ("username", "email", "first_name", "last_name"):
            try:
                UserModel._meta.get_field(key)
                filters |= Q(**{f"{key}__icontains": q})
            except Exception:
                continue
        filters |= Q(groups__name__icontains=q)
        qs = qs.filter(filters).distinct()

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    return render(request, "admin/employees_list.html", {"page_obj": page_obj, "q": q})


@system_staff_required
def system_employee_create(request):
    if request.method == "POST":
        form = SystemEmployeeCreateForm(request.POST)
        # منع غير السوبر من إنشاء superuser
        if not getattr(request.user, "is_superuser", False):
            form.fields["role"].choices = [
                (SystemEmployeeCreateForm.ROLE_SUPPORT, "موظف دعم"),
            ]
        else:
            form.fields["role"].choices = [
                (SystemEmployeeCreateForm.ROLE_SUPPORT, "موظف دعم"),
                (SystemEmployeeCreateForm.ROLE_SUPERUSER, "مدير نظام (superuser)"),
            ]

        if form.is_valid():
            role = form.cleaned_data.get("role")
            if role == SystemEmployeeCreateForm.ROLE_SUPERUSER and not getattr(request.user, "is_superuser", False):
                raise PermissionDenied("لا تملك صلاحية إنشاء مدير نظام.")

            form.save()
            messages.success(request, "تم إنشاء الموظف بنجاح.")
            return redirect("dashboard:system_employees_list")

        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SystemEmployeeCreateForm()
        if getattr(request.user, "is_superuser", False):
            form.fields["role"].choices = [
                (SystemEmployeeCreateForm.ROLE_SUPPORT, "موظف دعم"),
                (SystemEmployeeCreateForm.ROLE_SUPERUSER, "مدير نظام (superuser)"),
            ]

    return render(request, "admin/employee_form.html", {"form": form})


@system_staff_required
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

    # موظف الدعم لا يُسمح له بترقية المستخدمين إلى staff/superuser
    if not getattr(request.user, "is_superuser", False):
        for f in ("is_staff", "is_superuser"):
            if f in form.fields:
                del form.fields[f]

    return render(request, "admin/user_edit.html", {"form": form, "is_create": True})


@system_staff_required
def system_user_edit(request, pk: int):
    user = get_object_or_404(UserModel, pk=pk)

    # موظف الدعم لا يعدّل حسابات السوبر
    if not getattr(request.user, "is_superuser", False) and getattr(user, "is_superuser", False):
        raise PermissionDenied("لا تملك صلاحية تعديل هذا المستخدم.")

    if request.method == "POST":
        form = SystemUserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بيانات المستخدم بنجاح.")
            return redirect("dashboard:system_users_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SystemUserUpdateForm(instance=user)

    # موظف الدعم لا يُسمح له بتعديل staff/superuser
    if not getattr(request.user, "is_superuser", False):
        for f in ("is_staff", "is_superuser"):
            if f in form.fields:
                del form.fields[f]

    return render(request, "admin/user_edit.html", {"form": form, "is_create": False, "user_obj": user})


@superuser_required
def system_user_delete(request, pk: int):
    user = get_object_or_404(UserModel, pk=pk)

    if request.method == "POST":
        username = getattr(user, "username", str(user.pk))
        user.delete()
        messages.success(request, f"تم حذف المستخدم {username}.")
        return redirect("dashboard:system_users_list")

    return render(request, "admin/user_delete_confirm.html", {"user_obj": user})


# =====================
# 💳 إدارة الاشتراكات
# =====================

def _get_subscription_model_robust():
    """
    1) لو عندك تطبيق subscriptions فعليًا: subscriptions.SchoolSubscription
    2) وإلا: استخدم core.SchoolSubscription (Legacy الموجود في core/models.py)
    """
    try:
        return apps.get_model("subscriptions", "SchoolSubscription")
    except Exception:
        try:
            return apps.get_model("core", "SchoolSubscription")
        except Exception:
            return None

def _get_subscription_model():
    return _get_subscription_model_robust()

@system_staff_required
def system_subscriptions_list(request):
    SubModel = _get_subscription_model_robust()

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()  # active | inactive | ""

    today = timezone.localdate()

    rows = []
    page_obj = None

    active_count = 0
    inactive_count = 0
    total_count = 0

    if SubModel is None:
        return render(
            request,
            "admin/subscriptions_list.html",
            {
                "rows": rows,
                "page_obj": page_obj,
                "q": q,
                "status": status,
                "active_count": 0,
                "inactive_count": 0,
                "total_count": 0,
            },
        )

    # ---------- بناء QuerySet مرن حسب الحقول ----------
    qs = SubModel.objects.all()

    # روابط شائعة
    has_school = True
    has_plan = True
    try:
        SubModel._meta.get_field("school")
    except Exception:
        has_school = False
    try:
        SubModel._meta.get_field("plan")
    except Exception:
        has_plan = False

    if has_school:
        try:
            qs = qs.select_related("school")
        except Exception:
            pass
    if has_plan:
        try:
            qs = qs.select_related("plan")
        except Exception:
            pass

    # فلترة البحث
    if q:
        filters = Q()
        if has_school:
            filters |= Q(school__name__icontains=q)
            # email في School غير موجود عندك في core/models.py → لن نفلتر عليه
        if has_plan:
            filters |= Q(plan__name__icontains=q)
        qs = qs.filter(filters).distinct()

    # ---------- توحيد منطق "نشط" بين النظامين ----------
    # New subscriptions عادة: starts_at/ends_at + status
    # Legacy core: start_date/end_date + is_active
    def _is_active_obj(sub) -> bool:
        # boolean مباشر لو موجود
        if hasattr(sub, "is_active"):
            try:
                if not bool(sub.is_active):
                    return False
            except Exception:
                pass

        # status لو موجود
        if hasattr(sub, "status"):
            try:
                if str(sub.status) == "cancelled":
                    return False
                # لو status == active غالباً يعني ساري (مع مراعاة التاريخ)
            except Exception:
                pass

        # ends_at / end_date
        end_val = getattr(sub, "ends_at", None)
        if end_val is None:
            end_val = getattr(sub, "end_date", None)

        if end_val:
            try:
                return end_val >= today
            except Exception:
                return True

        return True

    def _starts_at(sub):
        v = getattr(sub, "starts_at", None)
        if v is None:
            v = getattr(sub, "start_date", None)
        return v

    def _ends_at(sub):
        v = getattr(sub, "ends_at", None)
        if v is None:
            v = getattr(sub, "end_date", None)
        return v

    # أعداد الإجمالي/النشط/غير النشط (بدون كسر لو اختلفت الحقول)
    # نحاول DB أولاً إن أمكن، وإلا نحسب بعد جلب بسيط
    try:
        total_count = qs.count()
    except Exception:
        total_count = 0

    # فلترة حسب status من الرابط
    if status == "active":
        # أفضلية فلترة DB إن كان عندك is_active/end_date
        if hasattr(SubModel, "is_active") and (hasattr(SubModel, "end_date") or hasattr(SubModel, "ends_at")):
            # هذا فرع متسامح – لكن بعض الأنظمة لا تقبل هذا مباشرة
            # لذا نكتفي بفلترة Python في الصفحات
            pass
    elif status == "inactive":
        pass

    # ترتيب
    # new: -starts_at, -id | legacy: -start_date, -id
    if hasattr(SubModel, "starts_at"):
        qs = qs.order_by("-starts_at", "-id")
    elif hasattr(SubModel, "start_date"):
        qs = qs.order_by("-start_date", "-id")
    else:
        qs = qs.order_by("-id")

    # Pagination
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    # بناء rows جاهزة للقالب
    # + تطبيق فلتر active/inactive هنا بشكل نهائي وآمن
    filtered_rows = []
    for sub in page_obj.object_list:
        is_active = _is_active_obj(sub)

        if status == "active" and not is_active:
            continue
        if status == "inactive" and is_active:
            continue

        school_obj = getattr(sub, "school", None)
        plan_obj = getattr(sub, "plan", None)

        filtered_rows.append(
            {
                "id": sub.pk,
                "school_name": getattr(school_obj, "name", "") if school_obj else "—",
                "school_email": getattr(school_obj, "email", "") if school_obj else "",
                "plan_name": getattr(plan_obj, "name", "") if plan_obj else "—",
                "starts_at": _starts_at(sub),
                "ends_at": _ends_at(sub),
                "is_active": is_active,
            }
        )

    # حساب العدادات بشكل موثوق (على كامل qs) — بحساب بسيط
    # (لو كانت كبيرة جدًا لاحقًا نعملها Query-level حسب حقولك)
    try:
        all_list = list(qs[:2000])  # حد أمان
    except Exception:
        all_list = []

    if all_list:
        active_count = sum(1 for s in all_list if _is_active_obj(s))
        inactive_count = len(all_list) - active_count
        total_count = len(all_list)

    return render(
        request,
        "admin/subscriptions_list.html",
        {
            "rows": filtered_rows,
            "page_obj": page_obj,
            "q": q,
            "status": status,
            "active_count": active_count,
            "inactive_count": inactive_count,
            "total_count": total_count,
        },
    )


@system_staff_required
def system_subscription_create(request):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    plan_durations = {p.id: p.duration_days for p in SubscriptionPlan.objects.all().only("id", "duration_days")}
    plan_prices = {p.id: str(p.price) for p in SubscriptionPlan.objects.all().only("id", "price")}

    if request.method == "POST":
        form = SchoolSubscriptionForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            # احسب تاريخ النهاية تلقائيًا من مدة الخطة إذا كانت النهاية غير محددة.
            try:
                if not getattr(obj, "ends_at", None) and getattr(obj, "starts_at", None) and getattr(obj, "plan", None):
                    days = getattr(obj.plan, "duration_days", None)
                    if days is not None:
                        days_int = int(days)
                        if days_int > 0:
                            obj.ends_at = obj.starts_at + timedelta(days=days_int)
            except Exception:
                pass
            obj.save()

            # سجل طريقة الدفع عند إنشاء اشتراك مدفوع يدويًا (لا تشمل الباقة المجانية)
            try:
                from subscriptions.models import SubscriptionPaymentOperation

                plan_obj = getattr(obj, "plan", None)
                price = getattr(plan_obj, "price", 0) if plan_obj is not None else 0
                method = (form.cleaned_data.get("payment_method") or "").strip()

                if plan_obj is not None and float(price or 0) > 0:
                    if method:
                        SubscriptionPaymentOperation.objects.create(
                            school=getattr(obj, "school", None),
                            subscription=obj,
                            plan=plan_obj,
                            amount=price or 0,
                            method=method,
                            source="admin_manual",
                            created_by=request.user,
                        )
            except Exception:
                pass

            messages.success(request, "تم إنشاء الاشتراك بنجاح.")
            return redirect("dashboard:system_subscriptions_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSubscriptionForm()

    return render(
        request,
        "admin/subscription_form.html",
        {"form": form, "title": "إضافة اشتراك", "plan_durations": plan_durations, "plan_prices": plan_prices},
    )


@system_staff_required
def system_subscription_edit(request, pk: int):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    plan_durations = {p.id: p.duration_days for p in SubscriptionPlan.objects.all().only("id", "duration_days")}
    plan_prices = {p.id: str(p.price) for p in SubscriptionPlan.objects.all().only("id", "price")}

    obj = get_object_or_404(SubModel, pk=pk)

    if request.method == "POST":
        form = SchoolSubscriptionForm(request.POST, instance=obj)
        if form.is_valid():
            obj2 = form.save(commit=False)
            # احسب تاريخ النهاية تلقائيًا من مدة الخطة إذا كانت النهاية غير محددة.
            try:
                if not getattr(obj2, "ends_at", None) and getattr(obj2, "starts_at", None) and getattr(obj2, "plan", None):
                    days = getattr(obj2.plan, "duration_days", None)
                    if days is not None:
                        days_int = int(days)
                        if days_int > 0:
                            obj2.ends_at = obj2.starts_at + timedelta(days=days_int)
            except Exception:
                pass
            obj2.save()

            payment_method_saved_label = None
            payment_method_save_failed = False

            # حفظ/تحديث طريقة الدفع لاشتراك سابق (عملية دفع + فاتورة إن وجدت)
            try:
                from subscriptions.models import SubscriptionPaymentOperation

                plan_obj = getattr(obj2, "plan", None)
                price = getattr(plan_obj, "price", 0) if plan_obj is not None else 0
                method = (form.cleaned_data.get("payment_method") or "").strip()

                if plan_obj is not None and float(price or 0) > 0 and method:
                    # استخدم آخر عملية دفع موجودة للاشتراك (سواء كانت من طلب أو إضافة يدوية)
                    op = (
                        SubscriptionPaymentOperation.objects.filter(
                            school=getattr(obj2, "school", None),
                            subscription=obj2,
                        )
                        .order_by("-created_at", "-id")
                        .first()
                    )

                    if op is None:
                        op = SubscriptionPaymentOperation.objects.create(
                            school=getattr(obj2, "school", None),
                            subscription=obj2,
                            plan=plan_obj,
                            amount=price or 0,
                            method=method,
                            source="admin_manual",
                            created_by=request.user,
                            note="Updated via edit",
                        )
                    else:
                        changed = False
                        if getattr(op, "method", None) != method:
                            op.method = method
                            changed = True
                        if getattr(op, "plan_id", None) != getattr(plan_obj, "id", None):
                            op.plan = plan_obj
                            changed = True
                        try:
                            if float(getattr(op, "amount", 0) or 0) != float(price or 0):
                                op.amount = price or 0
                                changed = True
                        except Exception:
                            pass
                        if changed:
                            op.save(update_fields=["method", "plan", "amount"])

                    try:
                        payment_method_saved_label = getattr(op, "get_method_display", lambda: op.method)()
                    except Exception:
                        payment_method_saved_label = op.method

                    # تحديث/إنشاء الفاتورة بشكل منفصل حتى لا يمنع حفظ طريقة الدفع
                    try:
                        from django.template.loader import render_to_string

                        from subscriptions.invoicing import _get_seller_info, build_invoice_from_operation

                        try:
                            inv = getattr(op, "invoice", None)
                        except Exception:
                            inv = None

                        if inv is None:
                            build_invoice_from_operation(op)
                        else:
                            inv.payment_method = op.method
                            inv.amount = op.amount
                            inv.plan = op.plan
                            
                            # Fetch contact info
                            c_name, c_mobile = "", ""
                            try:
                                profile = inv.school.users.first()
                                if profile:
                                    c_name = f"{profile.user.first_name} {profile.user.last_name}".strip()
                                    c_mobile = profile.mobile
                            except Exception: pass

                            html = render_to_string(
                                "invoices/subscription_invoice.html",
                                {
                                    "invoice": inv,
                                    "seller": _get_seller_info(),
                                    "school": inv.school,
                                    "subscription": inv.subscription,
                                    "plan": inv.plan,
                                    "contact_name": c_name,
                                    "contact_mobile": c_mobile,
                                },
                            )
                            inv.html_snapshot = html
                            inv.save(update_fields=["payment_method", "amount", "plan", "html_snapshot"])
                    except Exception:
                        logger.exception("Failed to update/generate invoice for subscription %s", getattr(obj2, "pk", None))
            except Exception:
                logger.exception("Failed to update payment method for subscription %s", getattr(obj2, "pk", None))
                payment_method_save_failed = True

            if payment_method_save_failed:
                messages.warning(request, "تم حفظ الاشتراك، لكن تعذّر حفظ/تحديث طريقة الدفع. راجع سجل الأخطاء.")
            elif payment_method_saved_label:
                messages.success(request, f"تم حفظ طريقة الدفع: {payment_method_saved_label}.")

            messages.success(request, "تم تحديث بيانات الاشتراك.")
            return redirect("dashboard:system_subscriptions_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SchoolSubscriptionForm(instance=obj)

    return render(
        request,
        "admin/subscription_form.html",
        {"form": form, "title": "تعديل اشتراك", "edit": True, "plan_durations": plan_durations, "plan_prices": plan_prices},
    )


@superuser_required
@require_POST
def system_subscription_delete(request, pk: int):
    SubModel = _get_subscription_model()
    if SubModel is None:
        messages.error(request, "نظام الاشتراكات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    obj = get_object_or_404(SubModel, pk=pk)
    obj.delete()
    messages.warning(request, "تم حذف الاشتراك.")
    return redirect("dashboard:system_subscriptions_list")


@system_staff_required
def system_subscription_invoice_view(request, pk: int):
    """عرض الفاتورة (HTML snapshot) لعمليات الدفع."""
    from django.http import HttpResponse

    from subscriptions.models import SubscriptionInvoice

    invoice = get_object_or_404(SubscriptionInvoice.objects.select_related("school", "subscription", "plan"), pk=pk)
    html = (invoice.html_snapshot or "").strip()

    # كحل احتياطي: إن لم تُحفظ النسخة لأي سبب، نعيد توليدها.
    if not html:
        try:
            from django.template.loader import render_to_string

            from subscriptions.invoicing import _get_seller_info

            html = render_to_string(
                "invoices/subscription_invoice.html",
                {
                    "invoice": invoice,
                    "seller": _get_seller_info(),
                    "school": invoice.school,
                    "subscription": invoice.subscription,
                    "plan": invoice.plan,
                },
            )
            invoice.html_snapshot = html
            invoice.save(update_fields=["html_snapshot"])
        except Exception:
            html = ""

    if not html:
        messages.error(request, "تعذر عرض الفاتورة حاليًا.")
        return redirect("dashboard:system_subscriptions_list")

    return HttpResponse(html, content_type="text/html; charset=utf-8")


# ===============================
# 🧾 طلبات التجديد/الاشتراك (Admin)
# ===============================


@system_staff_required
def system_subscription_requests_list(request):
    Req = _get_subscription_request_model()
    if Req is None:
        messages.error(request, "نظام طلبات الاشتراك غير مثبت.")
        return redirect("dashboard:system_admin_dashboard")

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    req_type = (request.GET.get("type") or "").strip()

    try:
        qs = Req.objects.all()
        try:
            qs = qs.select_related("school", "plan", "created_by", "processed_by")
        except Exception:
            pass

        if q:
            qs = qs.filter(
                Q(school__name__icontains=q)
                | Q(school__slug__icontains=q)
                | Q(plan__name__icontains=q)
            )

        if status:
            qs = qs.filter(status=status)
        if req_type:
            qs = qs.filter(request_type=req_type)

        qs = qs.order_by("-created_at", "-id")

        open_count = qs.filter(status__in=["submitted", "under_review"]).count()
        approved_count = qs.filter(status="approved").count()
        rejected_count = qs.filter(status="rejected").count()

        paginator = Paginator(qs, 25)
        page_obj = paginator.get_page(request.GET.get("page") or 1)
    except (ProgrammingError, OperationalError):
        # غالباً: لم يتم تشغيل migrate في البيئة (Render) بعد نشر الكود.
        messages.error(request, "قاعدة البيانات غير محدثة (جدول طلبات الاشتراك غير موجود). نفّذ migrate ثم أعد المحاولة.")
        open_count = 0
        approved_count = 0
        rejected_count = 0
        page_obj = Paginator([], 25).get_page(1)

    return render(
        request,
        "admin/subscription_requests_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "status": status,
            "type": req_type,
            "open_count": open_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
        },
    )


@system_staff_required
def system_subscription_request_detail(request, pk: int):
    Req = _get_subscription_request_model()
    if Req is None:
        messages.error(request, "نظام طلبات الاشتراك غير مثبت.")
        return redirect("dashboard:system_admin_dashboard")

    try:
        obj = get_object_or_404(Req, pk=pk)
    except (ProgrammingError, OperationalError):
        messages.error(request, "قاعدة البيانات غير محدثة (جدول طلبات الاشتراك غير موجود). نفّذ migrate ثم أعد المحاولة.")
        return redirect("dashboard:system_subscription_requests_list")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        admin_note = (request.POST.get("admin_note") or "").strip()

        if action not in {"approve", "reject", "under_review"}:
            messages.error(request, "إجراء غير صالح.")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

        if obj.status == "approved" and action == "approve":
            messages.info(request, "هذا الطلب معتمد بالفعل.")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

        if obj.status == "rejected" and action == "reject":
            messages.info(request, "هذا الطلب مرفوض بالفعل.")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

        if action == "under_review":
            if obj.status in {"approved", "rejected"}:
                messages.warning(request, "لا يمكن تغيير حالة طلب مُعالج.")
                return redirect("dashboard:system_subscription_request_detail", pk=pk)
            obj.status = "under_review"
            obj.admin_note = admin_note
            obj.processed_by = request.user
            obj.processed_at = timezone.now()
            obj.save(update_fields=["status", "admin_note", "processed_by", "processed_at", "updated_at"])
            messages.success(request, "تم تحويل الطلب إلى (قيد المراجعة).")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

        if action == "reject":
            if obj.status == "approved":
                messages.warning(request, "لا يمكن رفض طلب مُعتمد.")
                return redirect("dashboard:system_subscription_request_detail", pk=pk)
            obj.status = "rejected"
            obj.admin_note = admin_note
            obj.processed_by = request.user
            obj.processed_at = timezone.now()
            obj.save(update_fields=["status", "admin_note", "processed_by", "processed_at", "updated_at"])
            messages.success(request, "تم رفض الطلب.")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

        if action == "approve":
            if obj.status == "rejected":
                messages.warning(request, "لا يمكن اعتماد طلب مرفوض.")
                return redirect("dashboard:system_subscription_request_detail", pk=pk)

            SubNew = None
            try:
                SubNew = apps.get_model("subscriptions", "SchoolSubscription")
            except Exception:
                SubNew = None
            if SubNew is None:
                messages.error(request, "موديل الاشتراكات غير متوفر لإنشاء الاشتراك.")
                return redirect("dashboard:system_subscription_request_detail", pk=pk)

            with transaction.atomic():
                # منع التكرار وفق unique constraint
                sub_obj, _ = SubNew.objects.get_or_create(
                    school=obj.school,
                    plan=obj.plan,
                    starts_at=obj.requested_starts_at,
                    defaults={
                        "status": "active",
                        "notes": f"Approved from request #{obj.pk}",
                    },
                )

                obj.status = "approved"
                obj.admin_note = admin_note
                obj.processed_by = request.user
                obj.processed_at = timezone.now()
                obj.approved_subscription = sub_obj
                obj.save(
                    update_fields=[
                        "status",
                        "admin_note",
                        "processed_by",
                        "processed_at",
                        "approved_subscription",
                        "updated_at",
                    ]
                )

                # إنشاء عملية دفع لطلبات الاشتراك المدفوعة (لإنشاء الفاتورة تلقائياً عبر signals)
                try:
                    from subscriptions.models import SubscriptionPaymentOperation

                    amt = getattr(obj, "amount", 0) or 0
                    if float(amt) > 0 and not SubscriptionPaymentOperation.objects.filter(
                        school=obj.school,
                        subscription=sub_obj,
                        source="request",
                    ).exists():
                        SubscriptionPaymentOperation.objects.create(
                            school=obj.school,
                            subscription=sub_obj,
                            plan=obj.plan,
                            amount=amt,
                            method="bank_transfer",
                            source="request",
                            created_by=request.user,
                            note=f"Approved from request #{obj.pk}",
                        )
                except Exception:
                    pass

            messages.success(request, "تم اعتماد الطلب وإنشاء/ربط الاشتراك.")
            return redirect("dashboard:system_subscription_request_detail", pk=pk)

    return render(request, "admin/subscription_request_detail.html", {"obj": obj})


# ==========================
# ✅ اشتراكي (مدرسة المستخدم)
# ==========================

@login_required
def my_subscription(request):
    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    SubModel = _get_subscription_model()
    today = timezone.localdate()

    current_subscription = None
    upcoming_subscription = None
    primary_subscription = None
    primary_label = ""

    current_status_code = "none"
    current_status_label = "لا يوجد اشتراك"
    current_status_badge_class = "bg-rose-50 text-rose-700"

    def _field_exists(model_cls, field_name: str) -> bool:
        try:
            model_cls._meta.get_field(field_name)
            return True
        except Exception:
            return False

    def _get_attr(obj, name: str, default=None):
        try:
            return getattr(obj, name)
        except Exception:
            return default

    def _compute_display_ends_at(sub, start_field: str | None, end_field: str | None):
        if sub is None:
            return None
        end_value = _get_attr(sub, end_field) if end_field else None
        if end_value:
            return end_value

        plan = _get_attr(sub, "plan")
        start_value = _get_attr(sub, start_field) if start_field else None
        if plan is not None and start_value:
            try:
                days = _get_attr(plan, "duration_days")
                if days is not None:
                    days_int = int(days)
                    if days_int > 0:
                        return start_value + timedelta(days=days_int)
            except Exception:
                pass

        return None

    def _attach_display_fields(sub, start_field: str | None, end_field: str | None):
        if sub is None:
            return
        display_starts_at = _get_attr(sub, start_field) if start_field else None
        display_ends_at = _compute_display_ends_at(sub, start_field, end_field)
        try:
            setattr(sub, "display_starts_at", display_starts_at)
            setattr(sub, "display_ends_at", display_ends_at)
            if display_ends_at:
                setattr(sub, "display_days_left", max(0, int((display_ends_at - today).days)))
            else:
                setattr(sub, "display_days_left", None)
        except Exception:
            pass

    def _status_for(sub, start_field: str | None, end_field: str | None, status_field: str | None, is_active_field: str | None):
        if sub is None:
            return "none", "لا يوجد اشتراك", "bg-rose-50 text-rose-700"

        raw_status = _get_attr(sub, status_field) if status_field else None
        is_active_flag = _get_attr(sub, is_active_field) if is_active_field else None

        start_value = _get_attr(sub, start_field) if start_field else None
        end_value = _compute_display_ends_at(sub, start_field, end_field)

        if raw_status == "cancelled" or (raw_status is None and is_active_flag is False):
            return "cancelled", "ملغى", "bg-rose-50 text-rose-700"

        if raw_status == "pending":
            return "pending", "قيد الإعداد", "bg-amber-50 text-amber-700"

        if raw_status == "active" or (raw_status is None and is_active_flag is True):
            if start_value and start_value > today:
                return "upcoming", "لم يبدأ بعد", "bg-amber-50 text-amber-700"
            if end_value and end_value < today:
                return "expired", "منتهي", "bg-rose-50 text-rose-700"
            return "active", "سارية", "bg-emerald-50 text-emerald-700"

        if isinstance(raw_status, str) and raw_status:
            return raw_status, "غير معروف", "bg-slate-100 text-slate-700"

        return "unknown", "غير معروف", "bg-slate-100 text-slate-700"

    if SubModel is not None:
        start_field = "starts_at" if _field_exists(SubModel, "starts_at") else ("start_date" if _field_exists(SubModel, "start_date") else None)
        end_field = "ends_at" if _field_exists(SubModel, "ends_at") else ("end_date" if _field_exists(SubModel, "end_date") else None)
        status_field = "status" if _field_exists(SubModel, "status") else None
        is_active_field = "is_active" if _field_exists(SubModel, "is_active") else None

        qs = SubModel.objects.filter(school=school)

        # الاشتراك الحالي (ساري ضمن اليوم)
        current_qs = qs
        if status_field:
            current_qs = current_qs.filter(status="active")
        elif is_active_field:
            current_qs = current_qs.filter(is_active=True)
        if start_field:
            current_qs = current_qs.filter(**{f"{start_field}__lte": today})
        if end_field:
            current_qs = current_qs.filter(Q(**{f"{end_field}__isnull": True}) | Q(**{f"{end_field}__gte": today}))
        if start_field:
            current_qs = current_qs.order_by(f"-{start_field}", "-id")
        else:
            current_qs = current_qs.order_by("-id")
        current_subscription = current_qs.first()

        # الاشتراك القادم (أقرب اشتراك يبدأ في المستقبل)
        upcoming_qs = qs
        if status_field:
            upcoming_qs = upcoming_qs.filter(status__in=["active", "pending"])
        elif is_active_field:
            upcoming_qs = upcoming_qs.filter(is_active=True)
        if start_field:
            upcoming_qs = upcoming_qs.filter(**{f"{start_field}__gt": today}).order_by(start_field, "id")
            upcoming_subscription = upcoming_qs.first()

        _attach_display_fields(current_subscription, start_field, end_field)
        _attach_display_fields(upcoming_subscription, start_field, end_field)

        current_status_code, current_status_label, current_status_badge_class = _status_for(
            current_subscription,
            start_field,
            end_field,
            status_field,
            is_active_field,
        )

        primary_subscription = current_subscription or upcoming_subscription
        primary_label = "الاشتراك الحالي" if current_subscription else ("الاشتراك القادم" if upcoming_subscription else "")

    # ==========================
    # طلبات الاشتراك/التجديد
    # ==========================
    RequestModel = _get_subscription_request_model()
    renew_form = SubscriptionRenewalRequestForm(prefix="renew")
    new_form = SubscriptionNewRequestForm(prefix="new")

    def _shorten_receipt_filename(file_obj, *, prefix: str) -> Any:
        """Keep the stored ImageField path short (DB safety).

        Some production DBs may still have receipt_image as varchar(100) until migrations run.
        By shortening the uploaded filename we avoid 500s even before the ALTER migration.
        """
        if not file_obj:
            return file_obj
        original_name = (getattr(file_obj, "name", "") or "").strip()
        _base, ext = os.path.splitext(original_name)
        ext = (ext or ".jpg").lower()
        # keep extension sane
        if len(ext) > 10:
            ext = ext[:10]
        stamp = timezone.now().strftime("%Y%m%d%H%M%S")
        token = get_random_string(6)
        try:
            file_obj.name = f"{prefix}_{stamp}_{token}{ext}"
        except Exception:
            pass
        return file_obj

    # خطط الاشتراك (لإظهار تفاصيل الخطة في الواجهة)
    try:
        available_plans = list(
            SubscriptionPlan.objects.filter(is_active=True).order_by("sort_order", "name", "id")
        )
    except Exception:
        available_plans = []

    # تأكيد أن نموذج الاشتراك الجديد يستخدم نفس القائمة حتى عند POST
    try:
        new_form.fields["plan"].queryset = SubscriptionPlan.objects.filter(is_active=True).order_by(
            "sort_order", "name", "id"
        )
    except Exception:
        pass

    def _plan_details(plan_obj):
        if plan_obj is None:
            return None
        try:
            price = getattr(plan_obj, "price", None)
            duration_days = getattr(plan_obj, "duration_days", None)
            max_screens = getattr(plan_obj, "max_screens", None)
            return {
                "id": getattr(plan_obj, "pk", None),
                "name": getattr(plan_obj, "name", ""),
                "price": str(price) if price is not None else "",
                "duration_days": int(duration_days) if duration_days not in (None, "") else None,
                "max_screens": int(max_screens) if max_screens not in (None, "") else None,
            }
        except Exception:
            return None

    plans_map = {}
    for p in available_plans:
        d = _plan_details(p)
        if d and d.get("id") is not None:
            plans_map[str(d["id"])] = d

    renewal_plan_obj = None
    if current_subscription is not None:
        renewal_plan_obj = getattr(current_subscription, "plan", None)
    elif upcoming_subscription is not None:
        renewal_plan_obj = getattr(upcoming_subscription, "plan", None)
    elif primary_subscription is not None:
        renewal_plan_obj = getattr(primary_subscription, "plan", None)

    active_request_tab = "renewal" if renewal_plan_obj is not None else "new"

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action in {"renewal", "new"}:
            active_request_tab = action

        if RequestModel is None:
            messages.error(request, "ميزة طلبات الاشتراك غير متاحة حالياً.")
            return redirect("dashboard:my_subscription")

        if action not in {"renewal", "new"}:
            messages.error(request, "طلب غير صالح.")
            return redirect("dashboard:my_subscription")

        has_open = RequestModel.objects.filter(
            school=school,
            status__in=["submitted", "under_review"],
        ).exists()
        if has_open:
            messages.warning(request, "لديكم طلب قيد المراجعة بالفعل. الرجاء انتظار الرد قبل إرسال طلب جديد.")
            return redirect("dashboard:my_subscription")

        if action == "renewal":
            renew_form = SubscriptionRenewalRequestForm(request.POST, request.FILES, prefix="renew")
            if renew_form.is_valid():
                plan_obj = None
                if current_subscription is not None:
                    plan_obj = getattr(current_subscription, "plan", None)
                elif upcoming_subscription is not None:
                    plan_obj = getattr(upcoming_subscription, "plan", None)
                elif primary_subscription is not None:
                    plan_obj = getattr(primary_subscription, "plan", None)

                if plan_obj is None:
                    messages.error(request, "لا توجد خطة حالية يمكن تجديدها. استخدم طلب اشتراك جديد.")
                else:
                    RequestModel.objects.create(
                        school=school,
                        created_by=request.user,
                        request_type="renewal",
                        plan=plan_obj,
                        requested_starts_at=timezone.localdate(),
                        amount=getattr(plan_obj, "price", 0) or 0,
                        receipt_image=_shorten_receipt_filename(
                            renew_form.cleaned_data["receipt_image"],
                            prefix="renewal_receipt",
                        ),
                        transfer_note=renew_form.cleaned_data.get("transfer_note", "") or "",
                        status="submitted",
                    )
                    messages.success(request, "تم إرسال طلب التجديد بنجاح. سيتم مراجعته من الإدارة.")
                    return redirect("dashboard:my_subscription")
            else:
                messages.error(request, "الرجاء تصحيح الأخطاء في نموذج التجديد.")

        if action == "new":
            new_form = SubscriptionNewRequestForm(request.POST, request.FILES, prefix="new")
            try:
                new_form.fields["plan"].queryset = SubscriptionPlan.objects.filter(is_active=True).order_by(
                    "sort_order", "name", "id"
                )
            except Exception:
                pass
            if new_form.is_valid():
                plan_obj = new_form.cleaned_data["plan"]
                RequestModel.objects.create(
                    school=school,
                    created_by=request.user,
                    request_type="new",
                    plan=plan_obj,
                    requested_starts_at=timezone.localdate(),
                    amount=getattr(plan_obj, "price", 0) or 0,
                    receipt_image=_shorten_receipt_filename(
                        new_form.cleaned_data["receipt_image"],
                        prefix="new_receipt",
                    ),
                    transfer_note=new_form.cleaned_data.get("transfer_note", "") or "",
                    status="submitted",
                )
                messages.success(request, "تم إرسال طلب الاشتراك الجديد بنجاح. سيتم مراجعته من الإدارة.")
                return redirect("dashboard:my_subscription")
            messages.error(request, "الرجاء تصحيح الأخطاء في نموذج الاشتراك الجديد.")

    subscription_requests = []
    subscription_history = []
    if RequestModel is not None:
        try:
            subscription_requests = list(
                RequestModel.objects.filter(school=school)
                .select_related("plan", "processed_by", "approved_subscription")
                .order_by("-created_at", "-id")[:10]
            )
        except Exception:
            subscription_requests = []

    # ==========================
    # سجل العمليات: دمج الطلبات + الاشتراكات اليدوية
    # ==========================
    try:
        approved_sub_ids = set()
        if RequestModel is not None:
            approved_sub_ids = set(
                RequestModel.objects.filter(
                    school=school,
                    approved_subscription__isnull=False,
                ).values_list("approved_subscription_id", flat=True)
            )

        manual_subscriptions = []
        if SubModel is not None:
            manual_subscriptions = list(
                SubModel.objects.filter(school=school)
                .exclude(id__in=approved_sub_ids)
                .select_related("plan")
                .order_by("-created_at", "-id")[:10]
            )

        payment_ops_by_sub_id = {}
        try:
            from subscriptions.models import SubscriptionPaymentOperation

            sub_ids = [getattr(s, "pk", None) for s in manual_subscriptions if getattr(s, "pk", None) is not None]
            for r in subscription_requests:
                sid = getattr(r, "approved_subscription_id", None)
                if sid is not None:
                    sub_ids.append(sid)
            sub_ids = list({s for s in sub_ids if s is not None})

            if sub_ids:
                ops = (
                    SubscriptionPaymentOperation.objects.filter(
                        school=school,
                        subscription_id__in=sub_ids,
                    )
                    .prefetch_related("invoice")
                    .order_by("-created_at", "-id")
                )
                for op in ops:
                    sid = getattr(op, "subscription_id", None)
                    if sid and sid not in payment_ops_by_sub_id:
                        payment_ops_by_sub_id[sid] = op
        except Exception:
            payment_ops_by_sub_id = {}

        def _invoice_url_for_subscription_id(subscription_id: int | None) -> str | None:
            if not subscription_id:
                return None
            op = payment_ops_by_sub_id.get(subscription_id)
            if op is None:
                return None
            try:
                inv = getattr(op, "invoice", None)
            except Exception:
                inv = None
            if inv is None:
                return None
            try:
                return reverse("dashboard:subscription_invoice_view", kwargs={"pk": getattr(inv, "pk", None)})
            except Exception:
                return None

        for r in subscription_requests:
            receipt_url = None
            try:
                ri = getattr(r, "receipt_image", None)
                if ri and getattr(ri, "name", ""):
                    receipt_url = ri.url
            except Exception:
                receipt_url = None

            # طلبات الاشتراك الحالية تعتمد على رفع إيصال (تحويل بنكي)
            payment_method_label = "تحويل" if receipt_url else "—"
            try:
                amt = getattr(r, "amount", 0) or 0
                if float(amt) <= 0:
                    payment_method_label = "مجاني"
            except Exception:
                pass
            subscription_history.append(
                {
                    "date": getattr(r, "created_at", None),
                    "type_label": getattr(r, "get_request_type_display", lambda: "طلب")(),
                    "payment_method_label": payment_method_label,
                    "plan_name": getattr(getattr(r, "plan", None), "name", "—"),
                    "amount": getattr(r, "amount", None),
                    "status_code": getattr(r, "status", ""),
                    "status_label": getattr(r, "get_status_display", lambda: "")(),
                    "receipt_url": receipt_url,
                    "invoice_url": _invoice_url_for_subscription_id(getattr(r, "approved_subscription_id", None)),
                }
            )

        for s in manual_subscriptions:
            plan_obj = getattr(s, "plan", None)

            plan_price = 0
            try:
                plan_price = getattr(plan_obj, "price", 0) or 0
            except Exception:
                plan_price = 0

            payment_method_label = "غير محددة"
            try:
                if float(plan_price) <= 0:
                    payment_method_label = "مجاني"
                else:
                    op = payment_ops_by_sub_id.get(getattr(s, "pk", None))
                    if op is not None:
                        payment_method_label = getattr(op, "get_method_display", lambda: "غير محددة")()
            except Exception:
                pass

            subscription_history.append(
                {
                    "date": getattr(s, "created_at", None),
                    "type_label": "تفعيل يدوي",
                    "payment_method_label": payment_method_label,
                    "plan_name": getattr(plan_obj, "name", "—"),
                    "amount": plan_price,
                    "status_code": getattr(s, "status", ""),
                    "status_label": getattr(s, "get_status_display", lambda: "")(),
                    "receipt_url": None,
                    "invoice_url": _invoice_url_for_subscription_id(getattr(s, "pk", None)),
                }
            )

        safe_min_dt = timezone.make_aware(datetime(1970, 1, 1))
        subscription_history.sort(
            key=lambda x: (x.get("date") or safe_min_dt),
            reverse=True,
        )
        subscription_history = subscription_history[:10]
    except Exception:
        subscription_history = []

    return render(
        request,
        "dashboard/my_subscription.html",
        {
            "school": school,
            "subscription": primary_subscription,
            "primary_label": primary_label,

            "current_subscription": current_subscription,
            "current_status_code": current_status_code,
            "current_status_label": current_status_label,
            "current_status_badge_class": current_status_badge_class,

            "upcoming_subscription": upcoming_subscription,
            "today": today,

            "renew_form": renew_form,
            "new_form": new_form,
            "subscription_requests": subscription_requests,
            "subscription_history": subscription_history,

            "active_request_tab": active_request_tab,
            "renewal_plan_details": _plan_details(renewal_plan_obj),
            "plans_map": plans_map,
        },
    )


@login_required
def subscription_invoice_view(request, pk: int):
    """عرض الفاتورة للعميل (حسب المدرسة النشطة)."""
    from django.http import HttpResponse

    from subscriptions.models import SubscriptionInvoice

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    invoice = get_object_or_404(
        SubscriptionInvoice.objects.select_related("school", "subscription", "plan"),
        pk=pk,
    )

    # السماح للمشرفين (Superuser) بالوصول لأي فاتورة
    if not request.user.is_superuser:
        if getattr(invoice, "school_id", None) != getattr(school, "id", None):
            messages.error(request, "لا تملك صلاحية الوصول لهذه الفاتورة.")
            return redirect("dashboard:my_subscription")

    html = (invoice.html_snapshot or "").strip()
    if not html:
        try:
            from django.template.loader import render_to_string

            from subscriptions.invoicing import _get_seller_info

            html = render_to_string(
                "invoices/subscription_invoice.html",
                {
                    "invoice": invoice,
                    "seller": _get_seller_info(),
                    "school": invoice.school,
                    "subscription": invoice.subscription,
                    "plan": invoice.plan,
                },
            )
            invoice.html_snapshot = html
            invoice.save(update_fields=["html_snapshot"])
        except Exception:
            html = ""

    if not html:
        messages.error(request, "تعذر عرض الفاتورة حاليًا.")
        return redirect("dashboard:my_subscription")

    return HttpResponse(html, content_type="text/html; charset=utf-8")


# ==================
# Plans Management
# ==================

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_plans_list(request):
    plans = SubscriptionPlan.objects.all()
    return render(request, "admin/plans_list.html", {"plans": plans})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_plan_create(request):
    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء الخطة بنجاح")
            return redirect("dashboard:system_plans_list")
    else:
        form = SubscriptionPlanForm()
    return render(request, "admin/plan_form.html", {"form": form, "title": "إضافة خطة جديدة"})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_plan_edit(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    if request.method == "POST":
        form = SubscriptionPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث الخطة بنجاح")
            return redirect("dashboard:system_plans_list")
    else:
        form = SubscriptionPlanForm(instance=plan)
    return render(request, "admin/plan_form.html", {"form": form, "title": "تعديل الخطة"})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_plan_delete(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    if request.method == "POST":
        plan.delete()
        messages.success(request, "تم حذف الخطة بنجاح")
        return redirect("dashboard:system_plans_list")
    return render(request, "admin/plan_confirm_delete.html", {"plan": plan})

# ==================
# Reports
# ==================

@login_required
@user_passes_test(lambda u: u.is_superuser)
def system_reports(request):
    SubModel = _get_subscription_model()
    
    total_revenue = 0
    revenue_by_plan = []
    
    if SubModel is not None:
        # Total Revenue (Active Subscriptions)
        active_subs = SubModel.objects.filter(status="active")
        total_revenue = active_subs.aggregate(total=Sum("plan__price"))["total"] or 0
        
        # Revenue by Plan
        revenue_by_plan = (
            active_subs.values("plan__name")
            .annotate(total_revenue=Sum("plan__price"), count=Count("id"))
            .order_by("-total_revenue")
        )

    context = {
        "total_revenue": total_revenue,
        "revenue_by_plan": revenue_by_plan,
    }
    return render(request, "admin/reports.html", context)

# ==================
# Support Tickets (Admin)
# ==================

@login_required
@system_staff_required
def system_support_tickets(request):
    tickets = SupportTicket.objects.all().order_by("-created_at")
    return render(request, "admin/support_tickets.html", {"tickets": tickets})

@login_required
@system_staff_required
def system_support_ticket_detail(request, pk):
    ticket = get_object_or_404(SupportTicket, pk=pk)
    
    if request.method == "POST":
        # Handle status change
        if "status" in request.POST:
            ticket.status = request.POST["status"]
            ticket.save()
            messages.success(request, "تم تحديث حالة التذكرة.")
            return redirect("dashboard:system_support_ticket_detail", pk=pk)
            
        # Handle comment
        comment_form = TicketCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.ticket = ticket
            comment.user = request.user
            comment.save()
            messages.success(request, "تم إضافة الرد بنجاح.")
            return redirect("dashboard:system_support_ticket_detail", pk=pk)
    else:
        comment_form = TicketCommentForm()

    return render(request, "admin/support_ticket_detail.html", {
        "ticket": ticket,
        "comment_form": comment_form
    })

@login_required
@system_staff_required
def system_support_ticket_create(request):
    if request.method == "POST":
        form = SupportTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.user = request.user
            ticket.save()
            messages.success(request, "تم فتح التذكرة بنجاح")
            return redirect("dashboard:system_support_tickets")
    else:
        form = SupportTicketForm()
    return render(request, "admin/support_ticket_form.html", {"form": form})


# ==================
# Customer Support
# ==================

@login_required
def customer_support_tickets(request):
    tickets = SupportTicket.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "dashboard/support_tickets.html", {"tickets": tickets})

@login_required
def customer_support_ticket_detail(request, pk):
    ticket = get_object_or_404(SupportTicket, pk=pk, user=request.user)
    
    if request.method == "POST":
        comment_form = TicketCommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.ticket = ticket
            comment.user = request.user
            comment.save()
            messages.success(request, "تم إضافة الرد بنجاح.")
            return redirect("dashboard:customer_support_ticket_detail", pk=pk)
    else:
        comment_form = TicketCommentForm()

    return render(request, "dashboard/support_ticket_detail.html", {
        "ticket": ticket,
        "comment_form": comment_form
    })

@login_required
def customer_support_ticket_create(request):
    if request.method == "POST":
        form = CustomerSupportTicketForm(request.POST, user=request.user)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.user = request.user
            if hasattr(request.user, 'profile') and request.user.profile.active_school:
                ticket.school = request.user.profile.active_school
            ticket.save()
            messages.success(request, "تم فتح التذكرة بنجاح")
            return redirect("dashboard:customer_support_tickets")
    else:
        initial = {}
        subj = (request.GET.get("subject") or "").strip()
        msg = (request.GET.get("message") or "").strip()
        if subj:
            initial["subject"] = subj
        if msg:
            initial["message"] = msg
        form = CustomerSupportTicketForm(user=request.user, initial=initial)
    return render(request, "dashboard/support_ticket_form.html", {"form": form})


@manager_required
def request_screen_addon(request):
    """زر/صفحة طلب زيادة شاشات: يفتح تذكرة دعم مُعبأة تلقائيًا."""
    DisplayScreen = DisplayScreenModel()

    school, response = get_active_school_or_redirect(request)
    if response:
        return response

    current_count = DisplayScreen.objects.filter(school=school).count()
    max_screens = _get_school_max_screens_limit(school)
    plan_name = _get_school_effective_plan_label(school) or "—"

    school_name = (getattr(school, "name", "") or "").strip()
    subject = f"طلب زيادة شاشات - {school_name}" if school_name else "طلب زيادة شاشات"
    msg_lines = [
        f"المدرسة: {getattr(school, 'name', '')}",
        f"الخطة الحالية: {plan_name}",
        f"عدد الشاشات الحالية: {current_count}",
        f"الحد الحالي: {'غير محدود' if max_screens is None else int(max_screens)}",
        "",
        "المطلوب:",
        "- عدد الشاشات الإضافية: ",
        "- المدة: (شهر / نصف سنوي / سنوي)",
        "- ملاحظات: ",
    ]
    message_text = "\n".join(msg_lines)

    url = reverse("dashboard:customer_support_ticket_create")
    return redirect(f"{url}?subject={quote(subject)}&message={quote(message_text)}")


def _get_screen_addon_model():
    try:
        return apps.get_model("subscriptions", "SubscriptionScreenAddon")
    except Exception:
        return None


def _get_subscription_request_model():
    try:
        return apps.get_model("subscriptions", "SubscriptionRequest")
    except Exception:
        return None


@system_staff_required
def system_screen_addons_list(request):
    Addon = _get_screen_addon_model()
    if Addon is None:
        messages.error(request, "نظام زيادات الشاشات غير مثبت.")
        return redirect("dashboard:system_subscriptions_list")

    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    qs = Addon.objects.all()
    try:
        qs = qs.select_related("subscription", "subscription__school", "subscription__plan")
    except Exception:
        pass

    if q:
        qs = qs.filter(
            Q(subscription__school__name__icontains=q)
            | Q(subscription__school__slug__icontains=q)
            | Q(subscription__plan__name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    qs = qs.order_by("-created_at", "-id")

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    rows = []
    for obj in page_obj.object_list:
        sub = getattr(obj, "subscription", None)
        school_obj = getattr(sub, "school", None) if sub else None
        plan_obj = getattr(sub, "plan", None) if sub else None
        rows.append(
            {
                "id": obj.pk,
                "school_name": getattr(school_obj, "name", "—") if school_obj else "—",
                "plan_name": getattr(plan_obj, "name", "—") if plan_obj else "—",
                "screens_added": getattr(obj, "screens_added", 0) or 0,
                "pricing_cycle": getattr(obj, "pricing_cycle", "inherit") or "inherit",
                "validity_days": getattr(obj, "validity_days", None),
                "starts_at": getattr(obj, "starts_at", None),
                "ends_at": getattr(obj, "ends_at", None),
                "status": getattr(obj, "status", ""),
                "total_price": getattr(obj, "total_price", None),
            }
        )

    return render(
        request,
        "admin/screen_addons_list.html",
        {
            "rows": rows,
            "page_obj": page_obj,
            "q": q,
            "status": status,
        },
    )


@system_staff_required
def system_screen_addon_create(request):
    Addon = _get_screen_addon_model()
    if Addon is None:
        messages.error(request, "نظام زيادات الشاشات غير مثبت.")
        return redirect("dashboard:system_screen_addons_list")

    if request.method == "POST":
        form = SubscriptionScreenAddonForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء زيادة الشاشات بنجاح.")
            return redirect("dashboard:system_screen_addons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SubscriptionScreenAddonForm()

    return render(request, "admin/screen_addon_form.html", {"form": form, "title": "إضافة زيادة شاشات"})


@system_staff_required
def system_screen_addon_edit(request, pk: int):
    Addon = _get_screen_addon_model()
    if Addon is None:
        messages.error(request, "نظام زيادات الشاشات غير مثبت.")
        return redirect("dashboard:system_screen_addons_list")

    obj = get_object_or_404(Addon, pk=pk)

    if request.method == "POST":
        form = SubscriptionScreenAddonForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث زيادة الشاشات.")
            return redirect("dashboard:system_screen_addons_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = SubscriptionScreenAddonForm(instance=obj)

    return render(
        request,
        "admin/screen_addon_form.html",
        {"form": form, "title": "تعديل زيادة شاشات", "edit": True, "obj": obj},
    )


@superuser_required
def system_screen_addon_delete(request, pk: int):
    Addon = _get_screen_addon_model()
    if Addon is None:
        messages.error(request, "نظام زيادات الشاشات غير مثبت.")
        return redirect("dashboard:system_screen_addons_list")

    obj = get_object_or_404(Addon, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.warning(request, "تم حذف زيادة الشاشات.")
        return redirect("dashboard:system_screen_addons_list")

    return render(request, "admin/screen_addon_confirm_delete.html", {"obj": obj})
