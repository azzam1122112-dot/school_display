# schedule/models.py
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from core.models import School

# ============================================================
# Helpers
# ============================================================

WEEKDAYS = (
    (1, "الاثنين"),
    (2, "الثلاثاء"),
    (3, "الأربعاء"),
    (4, "الخميس"),
    (5, "الجمعة"),
    (6, "السبت"),
    (7, "الأحد"),
)


def _fmt(t: time | None) -> str:
    return t.strftime("%H:%M:%S") if isinstance(t, time) else "—"


def _overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    return max(a_start, b_start) < min(a_end, b_end)


def _to_dt(t: time) -> datetime:
    return datetime.combine(date(2000, 1, 1), t)


# ============================================================
# School Settings
# ============================================================

class SchoolSettings(models.Model):
    # Legacy stored values (kept for backward compatibility)
    THEME_DEFAULT = "default"
    THEME_BOYS = "boys"
    THEME_GIRLS = "girls"

    # New display theme keys (match CSS: body.display-board[data-theme="..."])
    THEME_INDIGO = "indigo"
    THEME_EMERALD = "emerald"
    THEME_ROSE = "rose"
    THEME_CYAN = "cyan"
    THEME_AMBER = "amber"
    THEME_ORANGE = "orange"
    THEME_VIOLET = "violet"

    THEME_CHOICES = [
        # Recommended themes
        (THEME_INDIGO, "أزرق/نيلي"),
        (THEME_EMERALD, "أخضر"),
        (THEME_ROSE, "وردي"),
        (THEME_CYAN, "سماوي"),
        (THEME_AMBER, "أصفر"),
        (THEME_ORANGE, "برتقالي"),
        (THEME_VIOLET, "بنفسجي"),

        # Legacy values (older dashboards stored these)
        (THEME_DEFAULT, "افتراضي (قديم)"),
        (THEME_BOYS, "مدارس البنين (قديم)"),
        (THEME_GIRLS, "مدارس البنات (قديم)"),
    ]

    show_home = models.BooleanField("إظهار الصفحة الرئيسية", default=True)
    show_settings = models.BooleanField("إظهار إعدادات المدرسة", default=True)
    show_change_password = models.BooleanField("إظهار تغيير كلمة المرور", default=True)
    show_screens = models.BooleanField("إظهار شاشات العرض", default=True)
    show_days = models.BooleanField("إظهار جداول الأيام", default=True)
    show_announcements = models.BooleanField("إظهار التنبيهات", default=True)
    show_excellence = models.BooleanField("إظهار قسم التميز", default=True)
    show_standby = models.BooleanField("إظهار حصص الانتظار", default=True)
    show_lessons = models.BooleanField("إظهار الحصص المجدولة", default=True)
    show_school_data = models.BooleanField("إظهار الفصول والمواد والمعلم/ـةون", default=True)

    FEATURE_PANEL_EXCELLENCE = "excellence"
    FEATURE_PANEL_DUTY = "duty"
    FEATURE_PANEL_CHOICES = [
        (FEATURE_PANEL_EXCELLENCE, "لوحة الشرف"),
        (FEATURE_PANEL_DUTY, "لوحة الإشراف والمناوبة"),
    ]

    featured_panel = models.CharField(
        "الكرت المميز في شاشة العرض",
        max_length=20,
        choices=FEATURE_PANEL_CHOICES,
        default=FEATURE_PANEL_EXCELLENCE,
        help_text="يحدد محتوى الكرت المميز في شاشة العرض لجميع شاشات المدرسة.",
    )

    school = models.OneToOneField(
        School,
        on_delete=models.CASCADE,
        related_name="schedule_settings",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )

    name = models.CharField("اسم المدرسة", max_length=150)
    logo_url = models.URLField("رابط الشعار", blank=True, null=True)

    theme = models.CharField(
        "الثيم/اللون",
        max_length=20,
        choices=THEME_CHOICES,
        default=THEME_DEFAULT,
    )

    timezone_name = models.CharField("المنطقة الزمنية", max_length=64, default="Asia/Riyadh")

    refresh_interval_sec = models.PositiveIntegerField(
        "فاصل تحديث الشاشة (ثوانٍ)",
        default=60,
        validators=[MinValueValidator(5)],
        help_text="عدد الثواني بين كل تحديث تلقائي للشاشة.",
    )
    standby_scroll_speed = models.FloatField(
        "سرعة تمرير الانتظار",
        default=0.8,
        validators=[MinValueValidator(0.05), MaxValueValidator(5.0)],
    )

    periods_scroll_speed = models.FloatField(
        "سرعة تمرير جدول الحصص",
        default=0.5,
        validators=[MinValueValidator(0.05), MaxValueValidator(5.0)],
    )

    display_accent_color = models.CharField(
        "لون شاشة العرض (اختياري)",
        max_length=7,
        blank=True,
        null=True,
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="أدخل لونًا بصيغة HEX مثل: #22C55E",
            )
        ],
        help_text="اختياري: اختر لوناً رئيسياً لشاشة العرض. اتركه فارغاً لاستخدام ألوان الثيم.",
    )

    class Meta:
        verbose_name = "إعداد المدرسة"
        verbose_name_plural = "إعدادات المدرسة"
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class DutyAssignment(models.Model):
    DUTY_SUPERVISION = "supervision"
    DUTY_DUTY = "duty"
    DUTY_CHOICES = [
        (DUTY_SUPERVISION, "إشراف"),
        (DUTY_DUTY, "مناوبة"),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="duty_assignments",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )
    date = models.DateField("التاريخ", default=timezone.localdate)
    teacher_name = models.CharField("اسم المعلم/ـة", max_length=100)
    duty_type = models.CharField("النوع", max_length=20, choices=DUTY_CHOICES)
    location = models.CharField("المكان (اختياري)", max_length=120, blank=True)
    priority = models.PositiveSmallIntegerField("ترتيب العرض", default=10)
    is_active = models.BooleanField("نشط", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "إشراف/مناوبة"
        verbose_name_plural = "الإشراف والمناوبة"
        ordering = ("date", "priority", "-id")
        indexes = [
            models.Index(fields=["school", "date"], name="duty_school_date_idx"),
            models.Index(fields=["school", "date", "duty_type"], name="duty_school_date_type"),
        ]

    def __str__(self) -> str:
        loc = f" — {self.location}" if self.location else ""
        return f"{self.date} — {self.teacher_name} — {self.get_duty_type_display()}{loc}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "teacher_name": self.teacher_name,
            "duty_type": self.duty_type,
            "duty_label": self.get_duty_type_display(),
            "location": self.location or "",
        }


# ============================================================
# Core Entities
# ============================================================

class SchoolClass(models.Model):
    settings = models.ForeignKey(
        SchoolSettings,
        on_delete=models.CASCADE,
        related_name="school_classes",
        verbose_name="إعدادات المدرسة",
    )
    name = models.CharField("اسم الصف", max_length=50)

    class Meta:
        verbose_name = "صف"
        verbose_name_plural = "الصفوف"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("settings", "name"), name="uq_sc_set_nm"),
        ]
        indexes = [
            models.Index(fields=("settings", "name"), name="ix_sc_set_nm"),
        ]

    def __str__(self) -> str:
        return self.name


class Subject(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="subjects",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )
    name = models.CharField("اسم المادة", max_length=100)

    class Meta:
        verbose_name = "مادة"
        verbose_name_plural = "المواد"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("school", "name"), name="uq_sub_sch_nm"),
        ]
        indexes = [
            models.Index(fields=("school", "name"), name="ix_sub_sch_nm"),
        ]

    def __str__(self) -> str:
        return self.name


class Teacher(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="teachers",
        verbose_name="المدرسة",
        null=True,
        blank=True,
    )
    name = models.CharField("اسم المعلم/ـة", max_length=100)

    class Meta:
        verbose_name = "معلم"
        verbose_name_plural = "المعلم/ـةون"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("school", "name"), name="uq_tch_sch_nm"),
        ]
        indexes = [
            models.Index(fields=("school", "name"), name="ix_tch_sch_nm"),
        ]

    def __str__(self) -> str:
        return self.name


# ============================================================
# Schedule
# ============================================================

class DaySchedule(models.Model):
    settings = models.ForeignKey(
        SchoolSettings,
        on_delete=models.CASCADE,
        related_name="day_schedules",
        verbose_name="إعدادات المدرسة",
    )
    weekday = models.PositiveSmallIntegerField("اليوم", choices=WEEKDAYS)
    is_active = models.BooleanField("يوم دراسي", default=True)
    periods_count = models.PositiveSmallIntegerField(
        "عدد الحصص",
        default=6,
        validators=[MinValueValidator(1)],
    )

    class Meta:
        verbose_name = "جدول يوم"
        verbose_name_plural = "جداول الأيام"
        ordering = ("weekday",)
        constraints = [
            models.UniqueConstraint(fields=("settings", "weekday"), name="uq_ds_set_wd"),
        ]
        indexes = [
            models.Index(fields=("settings", "weekday"), name="ix_ds_set_wd"),
        ]

    def __str__(self) -> str:
        return f"{self.settings.name} — {self.get_weekday_display()}"


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
        verbose_name="المعلم/ـة",
        null=True,
        blank=True,
    )

    index = models.PositiveSmallIntegerField("ترتيب الحصة (1..ن)", validators=[MinValueValidator(1)])
    starts_at = models.TimeField("يبدأ")
    ends_at = models.TimeField("ينتهي")

    class Meta:
        verbose_name = "حصة"
        verbose_name_plural = "الحصص"
        ordering = ("day__weekday", "index", "starts_at")
        constraints = [
            models.UniqueConstraint(fields=("day", "index"), name="uq_p_day_idx"),
        ]
        indexes = [
            models.Index(fields=("day", "starts_at"), name="ix_p_day_st"),
            models.Index(fields=("day", "ends_at"), name="ix_p_day_en"),
        ]

    def __str__(self) -> str:
        return f"حصة #{self.index} — {_fmt(self.starts_at)}→{_fmt(self.ends_at)}"

    def clean(self) -> None:
        if self.starts_at is None or self.ends_at is None:
            raise ValidationError("وقت البداية والنهاية مطلوبان.")
        if not (self.starts_at < self.ends_at):
            raise ValidationError({"ends_at": [f"وقت البداية يجب أن يكون قبل النهاية ({_fmt(self.starts_at)} < {_fmt(self.ends_at)})"]})

        if not self.day_id:
            return

        # تداخل مع حصص أخرى
        qs = Period.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for p in qs:
            if _overlap(self.starts_at, self.ends_at, p.starts_at, p.ends_at):
                raise ValidationError(f"تداخل مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})")

        # تداخل مع الفسح (بدون import دائري)
        BreakModel = apps.get_model("schedule", "Break")
        for b in BreakModel.objects.filter(day_id=self.day_id):
            if _overlap(self.starts_at, self.ends_at, b.starts_at, b.ends_at):
                raise ValidationError(f"تداخل مع الفسحة '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b.ends_at)})")


class Break(models.Model):
    day = models.ForeignKey(
        DaySchedule,
        on_delete=models.CASCADE,
        related_name="breaks",
        verbose_name="جدول اليوم",
    )
    label = models.CharField("تسمية الفسحة", max_length=50, default="فسحة")
    starts_at = models.TimeField("يبدأ")
    duration_min = models.PositiveSmallIntegerField(
        "المدة (دقائق)",
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(240)],
    )

    class Meta:
        verbose_name = "فسحة"
        verbose_name_plural = "فسح"
        ordering = ("day__weekday", "starts_at")
        indexes = [
            models.Index(fields=("day", "starts_at"), name="ix_b_day_st"),
        ]

    def __str__(self) -> str:
        return f"{self.label} — {_fmt(self.starts_at)} ({self.duration_min} د)"

    @property
    def ends_at(self) -> time:
        return (_to_dt(self.starts_at) + timedelta(minutes=int(self.duration_min))).time()

    def clean(self) -> None:
        if self.duration_min is None or int(self.duration_min) <= 0:
            raise ValidationError({"duration_min": ["المدة يجب أن تكون أكبر من صفر."]})
        if self.starts_at is None:
            raise ValidationError({"starts_at": ["هذا الحقل مطلوب."]})

        end_t = self.ends_at
        if not (self.starts_at < end_t):
            raise ValidationError({"starts_at": [f"البداية يجب أن تكون قبل النهاية ({_fmt(self.starts_at)} < {_fmt(end_t)})"]})

        if not self.day_id:
            return

        # تداخل مع فسح أخرى
        qs = Break.objects.filter(day_id=self.day_id).exclude(pk=self.pk)
        for b in qs:
            if _overlap(self.starts_at, end_t, b.starts_at, b.ends_at):
                raise ValidationError(f"تداخل مع '{b.label}' ({_fmt(b.starts_at)}-{_fmt(b.ends_at)})")

        # تداخل مع حصص
        PeriodModel = apps.get_model("schedule", "Period")
        for p in PeriodModel.objects.filter(day_id=self.day_id):
            if _overlap(self.starts_at, end_t, p.starts_at, p.ends_at):
                raise ValidationError(f"تداخل مع الحصة #{p.index} ({_fmt(p.starts_at)}-{_fmt(p.ends_at)})")


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
    period_index = models.PositiveSmallIntegerField("رقم الحصة", validators=[MinValueValidator(1)])
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
        verbose_name="المعلم/ـة",
    )
    is_active = models.BooleanField("مفعّلة", default=True)

    class Meta:
        verbose_name = "حصة مجدولة"
        verbose_name_plural = "الحصص المجدولة"
        ordering = ("settings", "weekday", "period_index", "school_class__name")
        constraints = [
            models.UniqueConstraint(fields=("settings", "weekday", "period_index", "school_class"), name="uq_cl_slot"),
        ]
        indexes = [
            models.Index(fields=("settings", "weekday", "period_index"), name="ix_cl_lookup"),
        ]

    def __str__(self) -> str:
        return f"{self.school_class} | {self.subject} | {self.teacher}"

    def clean(self) -> None:
        if not self.settings_id:
            return
        settings_school_id = self.settings.school_id
        if settings_school_id:
            if self.subject_id and self.subject.school_id and self.subject.school_id != settings_school_id:
                raise ValidationError({"subject": ["المادة لا تتبع لنفس المدرسة."]})
            if self.teacher_id and self.teacher.school_id and self.teacher.school_id != settings_school_id:
                raise ValidationError({"teacher": ["المعلم/ـة لا يتبع لنفس المدرسة."]})
