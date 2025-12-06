# dashboard/views.py
from __future__ import annotations

from datetime import datetime, date, time, timedelta
import csv
import io
import math

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Max
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .permissions import manager_required
from .forms import (
    SchoolSettingsForm, DayScheduleForm, PeriodFormSet, BreakFormSet,
    AnnouncementForm, ExcellenceForm, StandbyForm, DisplayScreenForm
)
from schedule.models import SchoolSettings, DaySchedule
from notices.models import Announcement, Excellence
from standby.models import StandbyAssignment
from core.models import DisplayScreen


# =========================
# ثوابت ومساعدات
# =========================

# أيام الأسبوع (الأحد → السبت)
SCHOOL_WEEK = [
    (0, "الأحد"),
    (1, "الاثنين"),
    (2, "الثلاثاء"),
    (3, "الأربعاء"),
    (4, "الخميس"),
    (5, "الجمعة"),
    (6, "السبت"),
]
WEEKDAY_MAP = dict(SCHOOL_WEEK)  # {0: "الأحد", ...}


def _collect_form_errors(*objs) -> str:
    """
    يجمع الأخطاء من النماذج والـFormSets بشكل آمن (يتعامل مع dict/list).
    يُعاد كسلسلة موحّدة لعرضها برسالة واحدة واضحة.
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
        # أخطاء عامة (non_form_errors) على النموذج أو الفورم-سِت
        if hasattr(obj, "non_form_errors"):
            _push(obj.non_form_errors())

        # لو كان FormSet: مر على النماذج الداخلية
        if hasattr(obj, "forms"):
            for f in obj.forms:
                if hasattr(f, "errors"):
                    if isinstance(f.errors, dict):
                        for elist in f.errors.values():
                            _push(elist)
                    else:
                        _push(f.errors)

        # أخطاء المستوى الأعلى
        if hasattr(obj, "errors"):
            errs = obj.errors
            if isinstance(errs, dict):
                for elist in errs.values():
                    _push(elist)
            elif isinstance(errs, (list, tuple)):
                # في بعض الإصدارات formset.errors -> list[dict]
                for item in errs:
                    if isinstance(item, dict):
                        for elist in item.values():
                            _push(elist)
                    else:
                        _push(item)

    # إزالة التكرارات مع الحفاظ على الترتيب
    seen, ordered = set(), []
    for m in msgs:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return " | ".join(ordered)


def _rev_manager(obj, preferred: str, fallback: str):
    """
    يرجع RelatedManager عكسي بأمان لاسمين محتملين (لدعم related_name المختلفة).
    مثال: periods / period_set ، breaks / break_set
    """
    mgr = getattr(obj, preferred, None)
    if mgr is None:
        mgr = getattr(obj, fallback)  # لو غير موجود سيثير AttributeError → يكشف المشكلة
    return mgr


def _parse_hhmm_or_hhmmss(s: str) -> time:
    """يدعم HH:MM أو HH:MM:SS برسالة خطأ عربية واضحة."""
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
    """تحويل آمن إلى int مع قيمة افتراضية وخيار السماح بالسالب."""
    try:
        x = int(val) if val not in (None, "",) else default
    except (TypeError, ValueError):
        x = default
    if not allow_negative and x < 0:
        raise ValueError("القيم لا يجوز أن تكون سالبة.")
    return x


# =========================
# المصادقة
# =========================

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
    """تسجيل دخول سريع للحساب التجريبي"""
    try:
        # البحث عن مستخدم الديمو
        user = User.objects.get(username="demo_user")
        
        # تسجيل الدخول يدوياً (Backend bypass)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
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
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'تم تغيير كلمة المرور بنجاح!')
            return redirect('dashboard:index')
        else:
            messages.error(request, 'الرجاء تصحيح الأخطاء أدناه.')
    else:
        form = PasswordChangeForm(request.user)
    return render(request, 'dashboard/change_password.html', {'form': form})


# =========================
# الرئيسية + إعدادات المدرسة
# =========================

@manager_required
def index(request):
    school = request.user.profile.school
    today = timezone.localdate()
    stats = {
        "ann_count": Announcement.objects.filter(school=school).count(),
        "exc_count": Excellence.objects.filter(school=school).count(),
        # عدّاد اليوم فقط (كان يحسب الكل سابقًا)
        "standby_today": StandbyAssignment.objects.filter(school=school, date=today).count(),
    }
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    return render(request, "dashboard/index.html", {"stats": stats, "settings": settings_obj})


@manager_required
def school_settings(request):
    school = request.user.profile.school
    obj, created = SchoolSettings.objects.get_or_create(
        school=school,
        defaults={"name": school.name}
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


# =========================
# جداول الأيام / الحصص / الفُسَح
# =========================

@manager_required
def days_list(request):
    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    if not settings_obj:
        messages.warning(request, "فضلاً أضف إعدادات المدرسة أولاً.")
        return redirect("dashboard:settings")

    # أنشئ أيام الأسبوع الدراسي فقط إن لم توجد
    existing = set(
        DaySchedule.objects.filter(settings=settings_obj, weekday__in=WEEKDAY_MAP.keys())
                           .values_list("weekday", flat=True)
    )
    for w in WEEKDAY_MAP.keys():
        if w not in existing:
            DaySchedule.objects.create(
                settings=settings_obj,
                weekday=w,
                periods_count=7 if w in (0, 1) else 6  # أحد/اثنين = 7، الباقي 6 (قابلة للتعديل)
            )

    days = list(
        DaySchedule.objects
        .filter(settings=settings_obj, weekday__in=WEEKDAY_MAP.keys())
        .order_by("weekday")
        .prefetch_related("periods", "breaks")
    )
    
    total_periods = 0
    for d in days:
        d.day_name = WEEKDAY_MAP.get(d.weekday, str(d.weekday))
        
        # Annotations for card
        d.breaks_count = d.breaks.count()
        
        periods = sorted(d.periods.all(), key=lambda p: p.starts_at)
        if periods:
            d.first_period_time = periods[0].starts_at.strftime("%H:%M")
            d.last_period_time = periods[-1].ends_at.strftime("%H:%M")
            
            # Calculate duration
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
    # السماح فقط بالأيام المعرفة
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
        # بادئات متطابقة مع القالب: p للحصص، b للفسح
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
        else:
            detail = _collect_form_errors(form, p_formset, b_formset)
            if not detail:
                # رسالة افتراضية واضحة تتماشى مع تحققات models/forms
                detail = "تحقق من الأوقات: يوجد حقول ناقصة/مكررة أو تداخلات زمنية."
            messages.error(request, detail)
            # لا نعيد التوجيه حتى لا تضيع المدخلات؛ نعيد نفس الصفحة بالبيانات
    else:
        form = DayScheduleForm(instance=day)
        p_formset = PeriodFormSet(instance=day, prefix="p")
        b_formset = BreakFormSet(instance=day, prefix="b")

    return render(request, "dashboard/day_edit.html", {
        "day": day,
        "form": form,
        "p_formset": p_formset,   # ← تعديل أوقات الحصص متاح بالكامل عبر هذا الـformset
        "b_formset": b_formset,   # ← تعديل/إضافة/حذف الفسح
    })


@manager_required
@transaction.atomic
def day_autofill(request, weekday: int):
    """
    تعبئة تلقائية لحصص اليوم + فسحة اختيارية (بدقة ثوانٍ).
    POST:
      start_time=HH:MM[:SS]
      period_minutes=int
      period_seconds=int
      gap_minutes=int
      gap_seconds=int
      break_after=int           # 0 = لا فسحة؛ 1..N = بعد رقم الحصة
      break_minutes=int         # أو break_duration رجوعاً للخلف
      break_seconds=int
    """
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
        gap_minutes    = _to_int(request.POST.get("gap_minutes"), 0)
        gap_seconds    = _to_int(request.POST.get("gap_seconds"), 0)
        break_after    = _to_int(request.POST.get("break_after"), 0)
        # دعم الاسم القديم break_duration
        break_minutes  = _to_int(request.POST.get("break_minutes") or request.POST.get("break_duration"), 0)
        break_seconds  = _to_int(request.POST.get("break_seconds"), 0)

        start_t = _parse_hhmm_or_hhmmss(start_time_str)

        p_len = timedelta(minutes=period_minutes, seconds=period_seconds)
        gap   = timedelta(minutes=gap_minutes,   seconds=gap_seconds)
        brk   = timedelta(minutes=break_minutes, seconds=break_seconds)

        if p_len.total_seconds() <= 0:
            raise ValueError("طول الحصة يجب أن يكون أكبر من صفر (دقائق/ثوانٍ).")

        if not day.periods_count or day.periods_count <= 0:
            messages.error(request, "عدد الحصص لليوم يساوي صفر. حدّد عدد الحصص أولاً ثم جرّب التعبئة.")
            return redirect("dashboard:day_edit", weekday=weekday)

        if break_after < 0 or break_after > day.periods_count:
            raise ValueError("قيمة 'الفسحة بعد الحصة رقم' خارج النطاق.")

        # مديري العلاقات (يدعم related_name المختلفة)
        periods_mgr = _rev_manager(day, "periods", "period_set")
        breaks_mgr  = _rev_manager(day, "breaks",  "break_set")

        base_date = timezone.localdate()
        cursor = datetime.combine(base_date, start_t)

        # حذف الحالي قبل الإنشاء لتفادي قيود التفرّد
        periods_mgr.all().delete()
        breaks_mgr.all().delete()

        # ⚠️ ملاحظة: نموذج Break يخزن الدقائق فقط؛ سنقوم بتقريب الثواني إلى الأعلى (ceil)
        # لضمان عدم فقدان أي ثانية تؤثر على نهاية الفسحة.
        break_minutes_final = int(math.ceil(max(0, brk.total_seconds()) / 60.0)) if brk.total_seconds() > 0 else 0

        for i in range(1, day.periods_count + 1):
            # أنشئ الحصة i
            start_period = cursor
            end_period = cursor + p_len
            periods_mgr.create(
                index=i,
                starts_at=start_period.time(),
                ends_at=end_period.time(),
            )
            cursor = end_period  # نهاية الحصة

            # أدخل الفسحة مباشرة بعد الحصة break_after (إن طُلبت)
            if break_minutes_final > 0 and break_after == i:
                breaks_mgr.create(
                    label="فسحة",
                    starts_at=cursor.time(),
                    duration_min=break_minutes_final,
                )
                cursor += timedelta(minutes=break_minutes_final)

            # فجوة بين الحصص (إن وجدت)
            cursor += gap

        messages.success(request, "تمت التعبئة التلقائية لجدول اليوم بدقة ثوانٍ وبدون تداخل.")
        return redirect("dashboard:day_edit", weekday=weekday)

    except Exception as e:
        # نجمع رسالة واضحة للمستخدم (من غير الكشف عن stacktrace)
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


# =========================
# التنبيهات
# =========================

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


# =========================
# قسم التميّز
# =========================

# ... بقية الاستيرادات
from .forms import ExcellenceForm  # تأكد أنك تستخدم النموذج الذي يحتوي photo

@manager_required
def exc_list(request):
    school = request.user.profile.school
    qs = Excellence.objects.filter(school=school).order_by("priority", "-start_at")
    
    now = timezone.now()
    # Active: start_at <= now AND (end_at IS NULL OR end_at > now)
    active_count = Excellence.objects.filter(
        Q(school=school) & Q(start_at__lte=now) & (Q(end_at__isnull=True) | Q(end_at__gt=now))
    ).count()
    
    # Expired: end_at <= now
    expired_count = Excellence.objects.filter(school=school, end_at__lte=now).count()
    
    # Max priority
    max_p = Excellence.objects.filter(school=school).aggregate(m=Max("priority"))["m"] or 0

    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    
    context = {
        "page": page,
        "active_count": active_count,
        "expired_count": expired_count,
        "max_priority": max_p,
    }
    return render(request, "dashboard/exc_list.html", context)

@manager_required
def exc_create(request):
    school = request.user.profile.school
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES)  # ← مهم
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
    school = request.user.profile.school
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES, instance=obj)  # ← مهم
        if form.is_valid():
            form.save()  # سيحفظ الملف المرفوع تلقائيًا إلى MEDIA_ROOT/upload_to
            messages.success(request, "تم تحديث بطاقة التميز.")
            return redirect("dashboard:exc_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = ExcellenceForm(instance=obj)
    return render(request, "dashboard/exc_form.html", {"form": form, "title": "تعديل تميز"})


@manager_required
def exc_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(Excellence, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف البطاقة.")
        return redirect("dashboard:exc_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")


# =========================
# حصص الانتظار
# =========================

@manager_required
def standby_list(request):
    school = request.user.profile.school
    qs = StandbyAssignment.objects.filter(school=school).order_by("-date", "period_index")
    
    # إحصائيات
    today = timezone.localdate()
    today_count = StandbyAssignment.objects.filter(school=school, date=today).count()
    teachers_count = StandbyAssignment.objects.filter(school=school).values("teacher_name").distinct().count()
    classes_count = StandbyAssignment.objects.filter(school=school).values("class_name").distinct().count()

    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    
    context = {
        "page": page,
        "today_count": today_count,
        "teachers_count": teachers_count,
        "classes_count": classes_count,
    }
    return render(request, "dashboard/standby_list.html", context)


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
    return render(request, "dashboard/standby_form.html", {"form": form, "title": "إضافة تكليف"})


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
    """
    استيراد CSV آمن:
    - يتحقق من الامتداد
    - يحاول تحويل التاريخ لـ YYYY-MM-DD
    - يتجاهل السجلات المعيبة بدل كسر العملية كاملة
    الأعمدة المتوقعة: date,period_index,class_name,teacher_name,notes
    """
    school = request.user.profile.school
    if request.method == "POST":
        f = request.FILES.get("file")
        if not f or not f.name.lower().endswith(".csv"):
            messages.error(request, "فضلاً أرفق ملف CSV صحيح.")
            return redirect("dashboard:standby_list")

        # قراءة الملف بالكامل كمصفوفة بايتات
        raw_data = f.read()
        decoded_file = None

        # محاولة فك التشفير بعدة صيغ شائعة (UTF-8, Windows-1256 للعربية, ISO-8859-1)
        for enc in ['utf-8-sig', 'windows-1256', 'iso-8859-1']:
            try:
                decoded_file = raw_data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        
        # إذا فشلت كل المحاولات، نستخدم utf-8 مع تجاهل الأخطاء
        if decoded_file is None:
             decoded_file = raw_data.decode('utf-8', errors='replace')

        data = io.StringIO(decoded_file)
        reader = csv.DictReader(data)
        count = 0
        for row in reader:
            try:
                # تحويل التاريخ إلى كائن date إن أمكن
                raw_date = (row.get("date") or "").strip()
                parsed_date: date
                try:
                    parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
                except ValueError:
                    # محاولة صيغة بديلة يوم/شهر/سنة
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
                # نتجاوز الصف المعيب بدون إيقاف العملية
                continue
        messages.success(request, f"تم استيراد {count} سجل.")
        return redirect("dashboard:standby_list")
    return render(request, "dashboard/standby_import.html")


@manager_required
@transaction.atomic
def day_clear(request, weekday: int):
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")
    if weekday not in WEEKDAY_MAP:
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسي.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    # يدعم related_name المختلفة
    periods_mgr = getattr(day, "periods", getattr(day, "period_set"))
    breaks_mgr  = getattr(day, "breaks", getattr(day, "break_set"))

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
        messages.error(request, "اليوم خارج أيام الأسبوع الدراسي.")
        return redirect("dashboard:days_list")

    school = request.user.profile.school
    settings_obj = SchoolSettings.objects.filter(school=school).first()
    day = get_object_or_404(DaySchedule, settings=settings_obj, weekday=weekday)

    periods_mgr = getattr(day, "periods", getattr(day, "period_set"))
    periods = list(periods_mgr.all())
    periods.sort(key=lambda p: (p.starts_at or time.min, p.ends_at or time.min))

    for i, p in enumerate(periods, start=1):
        if p.index != i:
            p.index = i
            p.save(update_fields=["index"])

    messages.success(request, "تمت إعادة ترقيم الحصص حسب الترتيب الزمني (1..ن).")
    return redirect("dashboard:day_edit", weekday=weekday)


# =========================
# شاشات العرض
# =========================

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
    return render(request, "dashboard/screen_form.html", {"form": form, "title": "إضافة شاشة"})


@manager_required
def screen_delete(request, pk: int):
    school = request.user.profile.school
    obj = get_object_or_404(DisplayScreen, pk=pk, school=school)
    if request.method == "POST":
        obj.delete()
        messages.success(request, "تم حذف الشاشة.")
        return redirect("dashboard:screen_list")
    return HttpResponseBadRequest("طريقة غير مدعومة.")
