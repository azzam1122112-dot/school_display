# schedule/models.py

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

from core.models import School


class SchoolSettings(models.Model):
    # ثوابت الثيمات
    THEME_DEFAULT = "default"   # الثيم الافتراضي (مناسب للجميع)
    THEME_BOYS = "boys"         # ثيم مدارس البنين
    THEME_GIRLS = "girls"       # ثيم مدارس البنات

    THEME_CHOICES = [
        (THEME_DEFAULT, "افتراضي"),
        (THEME_BOYS, "مدارس البنين"),
        (THEME_GIRLS, "مدارس البنات"),
    ]

    # تحكم في ظهور الأقسام داخل لوحة التحكم
    show_home = models.BooleanField("إظهار الصفحة الرئيسية", default=True)
    show_settings = models.BooleanField("إظهار إعدادات المدرسة", default=True)
    show_change_password = models.BooleanField("إظهار تغيير كلمة المرور", default=True)
    show_screens = models.BooleanField("إظهار شاشات العرض", default=True)
    show_days = models.BooleanField("إظهار جداول الأيام", default=True)
    show_announcements = models.BooleanField("إظهار التنبيهات", default=True)
    show_excellence = models.BooleanField("إظهار قسم التميز", default=True)
    show_standby = models.BooleanField("إظهار حصص الانتظار", default=True)
    show_lessons = models.BooleanField("إظهار الحصص المجدولة", default=True)
    show_school_data = models.BooleanField("إظهار الفصول والمواد والمعلمون", default=True)

    # ربط الإعدادات بمدرسة معيّنة (اختياري)
    school = models.OneToOneField(
        School,
        on_delete=models.CASCADE,
        related_name="schedule_settings",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )

    # معلومات عامة
    name = models.CharField("اسم المدرسة", max_length=150)
    logo_url = models.URLField("رابط الشعار", blank=True, null=True)

    # الثيم اللوني للعرض (3 ثيمات فقط)
    theme = models.CharField(
        "الثيم/اللون",
        max_length=50,
        default=THEME_DEFAULT,
        choices=THEME_CHOICES,
    )

    timezone_name = models.CharField(
        "المنطقة الزمنية",
        max_length=64,
        default="Asia/Riyadh",
    )

    # إعدادات الشاشة
    refresh_interval_sec = models.PositiveIntegerField(
        "فاصل تحديث الشاشة (ثوانٍ)",
        default=60,
        help_text="عدد الثواني بين كل تحديث تلقائي للشاشة.",
        validators=[MinValueValidator(5)],  # منع القيم الصغيرة جدًا
    )

    standby_scroll_speed = models.FloatField(
        "سرعة تمرير الانتظار",
        default=0.8,
        validators=[MinValueValidator(0.05), MaxValueValidator(5.0)],
        help_text="سرعة تمرير قائمة حصص الانتظار (من 0.05 إلى 5.0).",
    )

    periods_scroll_speed = models.FloatField(
        "سرعة تمرير جدول الحصص",
        default=0.5,
        validators=[MinValueValidator(0.05), MaxValueValidator(5.0)],
        help_text="سرعة حركة تمرير جدول الحصص على الشاشة الرئيسية (من 0.05 إلى 5.0).",
    )

    class Meta:
        verbose_name = "إعداد المدرسة"
        verbose_name_plural = "إعدادات المدرسة"

    def __str__(self) -> str:
        return self.name


class SchoolClass(models.Model):
    settings = models.ForeignKey(
        SchoolSettings,
        on_delete=models.CASCADE,
        related_name="school_classes",
        verbose_name="إعدادات المدرسة",
    )
    name = models.CharField("اسم الصف", max_length=50)

    class Meta:
        unique_together = ("settings", "name")
        ordering = ["name"]
        verbose_name = "صف"
        verbose_name_plural = "الصفوف"

    def __str__(self) -> str:
        return self.name


class Subject(models.Model):
    name = models.CharField("اسم المادة", max_length=100)

    class Meta:
        ordering = ["name"]
        verbose_name = "مادة"
        verbose_name_plural = "المواد"

    def __str__(self) -> str:
        return self.name


class Teacher(models.Model):
    name = models.CharField("اسم المعلم", max_length=100)

    class Meta:
        ordering = ["name"]
        verbose_name = "معلم"
        verbose_name_plural = "المعلمون"

    def __str__(self) -> str:
        return self.name


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
    return t.strftime("%H:%M:%S") if isinstance(t, time) else "—"


def _overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def _to_dt(t: time) -> datetime:
    return datetime.combine(date(2000, 1, 1), t)


class DaySchedule(models.Model):
    settings = models.ForeignKey(
        SchoolSettings,
        on_delete=models.CASCADE,
        related_name="day_schedules",
        verbose_name="إعدادات المدرسة",
    )
    weekday = models.PositiveSmallIntegerField("اليوم", choices=WEEKDAYS)
    is_active = models.BooleanField("يوم دراسي", default=True)
    periods_count = models.PositiveSmallIntegerField("عدد الحصص", default=6)

    class Meta:
        ordering = ("weekday",)
        constraints = [
            models.UniqueConstraint(
                fields=("settings", "weekday"),
                name="uniq_settings_weekday",
            ),
        ]
        indexes = [
            models.Index(
                fields=("settings", "weekday"),
                name="idx_settings_weekday",
            ),
        ]
        verbose_name = "جدول يوم"
        verbose_name_plural = "جداول الأيام"

    def __str__(self) -> str:
        return f"{self.settings.name} — {self.get_weekday_display()} ({self.periods_count} حصص)"


class Period(models.Model):
    day = models.ForeignKey(
        DaySchedule,
        on_delete=models.CASCADE,
        related_name="periods",
        verbose_name="جدول اليوم",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="periods",
        verbose_name="الصف",
        null=True,
        blank=True,
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="periods",
        verbose_name="المادة",
        null=True,
        blank=True,
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,
        related_name="periods",
        verbose_name="المعلم",
        null=True,
        blank=True,
    )
    index = models.PositiveSmallIntegerField("ترتيب الحصة (1..ن)")
    starts_at = models.TimeField("يبدأ")
    ends_at = models.TimeField("ينتهي")

    class Meta:
        ordering = ("day__weekday", "index", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("day", "index"),
                name="uniq_period_day_index",
            ),
        ]
        indexes = [
            models.Index(fields=("day", "starts_at"), name="idx_period_day_start"),
            models.Index(fields=("day", "ends_at"), name="idx_period_day_end"),
        ]
        verbose_name = "حصة"
        verbose_name_plural = "الحصص"

    def __str__(self) -> str:
        return f"حصة #{self.index} — {self.starts_at}→{self.ends_at}"

    def clean(self) -> None:
        errors: dict[str, list[str]] = {}

        if self.starts_at is None:
            errors.setdefault("starts_at", []).append("هذا الحقل مطلوب.")
        if self.ends_at is None:
            errors.setdefault("ends_at", []).append("هذا الحقل مطلوب.")
        if self.index is None or self.index == 0:
            errors.setdefault("index", []).append("الترتيب يجب أن يكون رقمًا موجبًا.")
        if errors:
            raise ValidationError(errors)

        if not (self.starts_at < self.ends_at):
            errors.setdefault("ends_at", []).append(
                f"وقت البداية يجب أن يكون قبل النهاية ({_fmt(self.starts_at)} < {_fmt(self.ends_at)})"
            )
            raise ValidationError(errors)

        if getattr(self, "_skip_cross_validation", False):
            return

        if not self.day_id:
            return

        is_full_day = (
            self.starts_at == time(0, 0, 0)
            and self.ends_at >= time(23, 59, 59)
        )

        siblings = Period.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for p in siblings:
            if is_full_day:
                raise ValidationError("لا يمكن إضافة حصة تغطي اليوم كله مع وجود حصص أخرى.")
            if _overlap(self.starts_at, self.ends_at, p.starts_at, p.ends_at):
                raise ValidationError(
                    f"تداخل مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})"
                )

        from .models import Break

        for b in Break.objects.filter(day_id=self.day_id):
            b_end = b.ends_at
            if is_full_day:
                raise ValidationError("لا يمكن إضافة حصة تغطي اليوم كله مع وجود فسح.")
            if _overlap(self.starts_at, self.ends_at, b.starts_at, b_end):
                raise ValidationError(
                    f"تداخل مع الفسحة '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b_end)})"
                )


class Break(models.Model):
    day = models.ForeignKey(
        DaySchedule,
        on_delete=models.CASCADE,
        related_name="breaks",
        verbose_name="جدول اليوم",
    )
    label = models.CharField("تسمية الفسحة", max_length=50, default="فسحة")
    starts_at = models.TimeField("يبدأ")
    duration_min = models.PositiveSmallIntegerField("المدة (دقائق)", default=20)

    class Meta:
        ordering = ("day__weekday", "starts_at")
        indexes = [
            models.Index(fields=("day", "starts_at"), name="idx_break_day_start"),
        ]
        verbose_name = "فسحة"
        verbose_name_plural = "فسح"

    def __str__(self) -> str:
        return f"{self.label} — {self.starts_at} ({self.duration_min} د)"

    @property
    def ends_at(self) -> time:
        return (_to_dt(self.starts_at) + timedelta(minutes=int(self.duration_min))).time()

    def clean(self) -> None:
        errors: dict[str, list[str]] = {}

        if self.duration_min is None or int(self.duration_min) <= 0:
            errors.setdefault("duration_min", []).append("المدة يجب أن تكون أكبر من صفر.")
        if self.starts_at is None:
            errors.setdefault("starts_at", []).append("هذا الحقل مطلوب.")
        if errors:
            raise ValidationError(errors)

        end_t = self.ends_at
        if not (self.starts_at < end_t):
            errors.setdefault("starts_at", []).append(
                f"البداية يجب أن تكون قبل النهاية ({_fmt(self.starts_at)} < {_fmt(end_t)})"
            )
            raise ValidationError(errors)

        if getattr(self, "_skip_cross_validation", False):
            return

        if not self.day_id:
            return

        is_full_day = (
            self.starts_at == time(0, 0, 0)
            and end_t >= time(23, 59, 59)
        )

        siblings = Break.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for b in siblings:
            if is_full_day:
                raise ValidationError("لا يمكن إضافة فسحة تغطي اليوم كله مع وجود أخرى.")
            if _overlap(self.starts_at, end_t, b.starts_at, b.ends_at):
                raise ValidationError(
                    f"تداخل مع '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b.ends_at)})"
                )

        for p in Period.objects.filter(day_id=self.day_id):
            if is_full_day:
                raise ValidationError("لا يمكن إضافة فسحة تغطي اليوم كله مع وجود حصص.")
            if _overlap(self.starts_at, end_t, p.starts_at, p.ends_at):
                raise ValidationError(
                    f"تداخل مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})"
                )


class ClassLesson(models.Model):
    settings = models.ForeignKey(
        SchoolSettings,
        on_delete=models.CASCADE,
        related_name="class_lessons",
        verbose_name="إعدادات المدرسة",
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="class_lessons",
        verbose_name="الصف",
    )
    weekday = models.PositiveSmallIntegerField("اليوم", choices=WEEKDAYS)
    period_index = models.PositiveSmallIntegerField("رقم الحصة")
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="class_lessons",
        verbose_name="المادة",
    )
    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.CASCADE,
        related_name="class_lessons",
        verbose_name="المعلم",
    )
    is_active = models.BooleanField("مفعّلة", default=True)

    class Meta:
        ordering = ("settings", "weekday", "period_index", "school_class__name")
        constraints = [
            models.UniqueConstraint(
                fields=("settings", "weekday", "period_index", "school_class"),
                name="uniq_classlesson_slot",
            ),
        ]
        indexes = [
            models.Index(
                fields=("settings", "weekday", "period_index"),
                name="idx_classlesson_lookup",
            ),
        ]
        verbose_name = "حصة مجدولة"
        verbose_name_plural = "الحصص المجدولة"

    def __str__(self) -> str:
        return (
            f"{self.settings.name} | {self.get_weekday_display()} | "
            f"حصة {self.period_index} | {self.school_class} | {self.subject} ({self.teacher})"
        )
