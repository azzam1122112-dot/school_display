# schedule/models.py
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from core.models import School

# ----------------------------
# ثوابت وأدوات مساعدة
# ----------------------------

WEEKDAYS = (
    (0, "الأحد"),
    (1, "الاثنين"),
    (2, "الثلاثاء"),
    (3, "الأربعاء"),
    (4, "الخميس"),
    (5, "الجمعة"),
    (6, "السبت"),
)


def _fmt(t: time | None) -> str:
    """تنسيق عرض الوقت بشكل HH:MM:SS مع حماية None."""
    return t.strftime("%H:%M:%S") if isinstance(t, time) else "—"


def _overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    """
    كشف التداخل بين فترتين زمنيتين داخل نفس اليوم.
    الشرط الرياضي الصارم: max(starts) < min(ends)
    - يسمح بالتلامس بدون تداخل (مثال: 07:00–07:45 لا يتداخل مع 07:45–08:30).
    """
    return max(a_start, b_start) < min(a_end, b_end)


def _to_dt(t: time) -> datetime:
    """تحويل time إلى datetime على تاريخ ثابت لتسهيل الحسابات (لا يعتمد على المنطقة الزمنية)."""
    return datetime.combine(date(2000, 1, 1), t)


# ----------------------------
# نماذج البيانات
# ----------------------------

class SchoolSettings(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="schedule_settings", verbose_name="المدرسة", null=True, blank=True)
    name = models.CharField("اسم المدرسة", max_length=150)
    logo_url = models.URLField("رابط الشعار", blank=True, null=True)
    theme = models.CharField("الثيم/اللون", max_length=50, default="default")
    timezone_name = models.CharField("المنطقة الزمنية", max_length=64, default="Asia/Riyadh")
    refresh_interval_sec = models.PositiveIntegerField("فاصل تحديث الشاشة (ث)", default=60)
    standby_scroll_speed = models.FloatField("سرعة تمرير الانتظار", default=0.8, help_text="القيمة الافتراضية 0.8. كلما زاد الرقم زادت السرعة.")

    class Meta:
        verbose_name = "إعداد المدرسة"
        verbose_name_plural = "إعدادات المدرسة"

    def __str__(self) -> str:
        return self.name


class DaySchedule(models.Model):
    settings = models.ForeignKey(
        SchoolSettings, on_delete=models.CASCADE, related_name="day_schedules"
    )
    weekday = models.PositiveSmallIntegerField("اليوم", choices=WEEKDAYS)
    is_active = models.BooleanField("يوم دراسي", default=True)
    periods_count = models.PositiveSmallIntegerField("عدد الحصص", default=6)

    class Meta:
        verbose_name = "جدول يوم"
        verbose_name_plural = "جداول الأيام"
        ordering = ("weekday",)
        constraints = [
            models.UniqueConstraint(
                fields=("settings", "weekday"), name="uniq_settings_weekday"
            ),
        ]
        indexes = [
            models.Index(fields=("settings", "weekday"), name="idx_settings_weekday"),
        ]

    def __str__(self) -> str:
        return f"{self.settings.name} — {self.get_weekday_display()} ({self.periods_count} حصص)"


class Period(models.Model):
    """
    تمثل حصة دراسية بوقت بداية ونهاية.
    - لا يُسمح بتداخل حصتين داخل نفس اليوم.
    - لا يُسمح بتداخل الحصة مع فسحة في نفس اليوم.
    - لا تُحفظ إلا إذا كانت البداية < النهاية.

    ملاحظة: لو قام الـForm بتعيين الراية `_skip_cross_validation = True` على الـinstance،
    فإن فحوص التداخل (مع الحصص/الفسح) سيتم تخطّيها هنا، بينما تظل فحوص الحقول الأساسية فعّالة.
    """
    day = models.ForeignKey(DaySchedule, on_delete=models.CASCADE, related_name="periods")
    index = models.PositiveSmallIntegerField("الترتيب (1..ن)")
    starts_at = models.TimeField("يبدأ")
    ends_at = models.TimeField("ينتهي")

    class Meta:
        verbose_name = "حصة"
        verbose_name_plural = "الحصص"
        ordering = ("day__weekday", "index", "starts_at")
        constraints = [
            models.UniqueConstraint(fields=("day", "index"), name="uniq_period_day_index"),
        ]
        indexes = [
            models.Index(fields=("day", "starts_at"), name="idx_period_day_start"),
            models.Index(fields=("day", "ends_at"), name="idx_period_day_end"),
        ]

    def __str__(self) -> str:
        return f"حصة #{self.index} — {self.starts_at}→{self.ends_at}"

    # ---- فحوص الصحة ----

    def clean(self):
        """
        تحقّقات شاملة:
        1) حقول مطلوبة
        2) starts_at < ends_at
        3) (اختياري) تخطي فحوص التداخل إذا طلب الـForm ذلك بالراية _skip_cross_validation
        4) منع التداخل مع الحصص الأخرى
        5) منع التداخل مع الفسح
        6) منع فترة تغطي اليوم كله بالتزامن مع أي فترة أخرى
        """
        errors: dict[str, list[str]] = {}

        # 1) حقول مطلوبة
        if self.starts_at is None:
            errors.setdefault("starts_at", []).append("هذا الحقل مطلوب.")
        if self.ends_at is None:
            errors.setdefault("ends_at", []).append("هذا الحقل مطلوب.")
        if self.index is None or self.index == 0:
            errors.setdefault("index", []).append("الترتيب يجب أن يكون رقمًا موجبًا (1..ن).")
        if errors:
            # لو حقول ناقصة، نوقف هنا برسائل واضحة
            raise ValidationError(errors)

        # 2) ترتيب زمني صحيح
        if not (self.starts_at < self.ends_at):
            errors.setdefault("ends_at", []).append(
                f"وقت بداية الحصة يجب أن يكون قبل نهايتها. ({_fmt(self.starts_at)} < {_fmt(self.ends_at)})"
            )
            raise ValidationError(errors)

        # 3) لو الـForm أشار لوجود أخطاء حقول سابقة، لا تُجري فحوص التداخل
        if getattr(self, "_skip_cross_validation", False):
            return

        # أثناء الإضافة عبر inline قد لا يكون day محفوظًا بعد
        if not self.day_id:
            return

        # حارس: فترة “اليوم الكامل” ممنوعة مع غيرها
        is_full_day = (self.starts_at == time(0, 0, 0) and self.ends_at >= time(23, 59, 59))

        # 4) ضد الحصص الأخرى
        siblings = Period.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for p in siblings:
            if is_full_day:
                raise ValidationError(
                    f"لا يمكن إضافة حصة تغطي اليوم كله ({_fmt(self.starts_at)}–{_fmt(self.ends_at)}) مع وجود حصص أخرى."
                )
            if _overlap(self.starts_at, self.ends_at, p.starts_at, p.ends_at):
                raise ValidationError(
                    f"تداخل وقت الحصة مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})."
                )

        # 5) ضد الفسح
        for b in Break.objects.filter(day_id=self.day_id):
            b_end = b.ends_at
            if is_full_day:
                raise ValidationError(
                    f"لا يمكن إضافة حصة تغطي اليوم كله ({_fmt(self.starts_at)}–{_fmt(self.ends_at)}) مع وجود فسح."
                )
            if _overlap(self.starts_at, self.ends_at, b.starts_at, b_end):
                raise ValidationError(
                    f"تداخل وقت الحصة مع الفسحة '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b_end)})."
                )


class Break(models.Model):
    """
    تمثل فسحة/استراحة داخل اليوم.
    - لا يُسمح بتداخل فسحتين داخل نفس اليوم.
    - لا يُسمح بتداخل الفسحة مع أي حصة.
    - مدة الفسحة موجبة، ونهايتها محسوبة من البداية + الدقائق.

    ملاحظة: لو قام الـForm بتعيين الراية `_skip_cross_validation = True` على الـinstance،
    فإن فحوص التداخل (مع الحصص/الفسح) سيتم تخطّيها هنا، بينما تظل فحوص الحقول الأساسية فعّالة.
    """
    day = models.ForeignKey(DaySchedule, on_delete=models.CASCADE, related_name="breaks")
    label = models.CharField("تسمية", max_length=50, default="فسحة")
    starts_at = models.TimeField("يبدأ")
    duration_min = models.PositiveSmallIntegerField("المدة (دقائق)", default=20)

    class Meta:
        verbose_name = "فسحة"
        verbose_name_plural = "فسح"
        ordering = ("day__weekday", "starts_at")
        indexes = [
            models.Index(fields=("day", "starts_at"), name="idx_break_day_start"),
        ]

    def __str__(self) -> str:
        return f"{self.label} — {self.starts_at} ({self.duration_min} د)"

    @property
    def ends_at(self) -> time:
        """نهاية الفسحة = البداية + المدة (دقائق)."""
        return (_to_dt(self.starts_at) + timedelta(minutes=int(self.duration_min))).time()

    # ---- فحوص الصحة ----

    def clean(self):
        """
        تحقّقات شاملة:
        1) مدة موجبة وبداية قبل النهاية
        2) (اختياري) تخطي فحوص التداخل إذا طلب الـForm ذلك بالراية _skip_cross_validation
        3) منع التداخل مع فسح أخرى
        4) منع التداخل مع الحصص
        5) منع “اليوم الكامل” بالتزامن مع أي فترة أخرى
        """
        errors: dict[str, list[str]] = {}

        # 1) صحة القيم الأساسية
        if self.duration_min is None or int(self.duration_min) <= 0:
            errors.setdefault("duration_min", []).append("مدة الفسحة يجب أن تكون أكبر من صفر.")
        if self.starts_at is None:
            errors.setdefault("starts_at", []).append("هذا الحقل مطلوب.")
        if errors:
            raise ValidationError(errors)

        end_t = self.ends_at
        if not (self.starts_at < end_t):
            errors.setdefault("starts_at", []).append(
                f"بداية الفسحة يجب أن تكون قبل نهايتها. ({_fmt(self.starts_at)} < {_fmt(end_t)})"
            )
            raise ValidationError(errors)

        # 2) لو الـForm أشار لوجود أخطاء حقول سابقة، لا تُجري فحوص التداخل
        if getattr(self, "_skip_cross_validation", False):
            return

        # أثناء الإضافة عبر inline قد لا يكون day محفوظًا بعد
        if not self.day_id:
            return

        # حارس: فترة “اليوم الكامل”
        is_full_day = (self.starts_at == time(0, 0, 0) and end_t >= time(23, 59, 59))

        # 3) ضد الفسح الأخرى
        siblings = Break.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for b in siblings:
            if is_full_day:
                raise ValidationError(
                    f"لا يمكن إضافة فسحة تغطي اليوم كله ({_fmt(self.starts_at)}–{_fmt(end_t)}) مع وجود فترات أخرى."
                )
            if _overlap(self.starts_at, end_t, b.starts_at, b.ends_at):
                raise ValidationError(
                    f"تداخل وقت الفسحة مع '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b.ends_at)})."
                )

        # 4) ضد الحصص
        for p in Period.objects.filter(day_id=self.day_id):
            if is_full_day:
                raise ValidationError(
                    f"لا يمكن إضافة فسحة تغطي اليوم كله ({_fmt(self.starts_at)}–{_fmt(end_t)}) مع وجود حصص."
                )
            if _overlap(self.starts_at, end_t, p.starts_at, p.ends_at):
                raise ValidationError(
                    f"تداخل وقت الفسحة مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})."
                )
