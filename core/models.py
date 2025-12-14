# core/models.py
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class School(models.Model):
    name = models.CharField("اسم المدرسة", max_length=150)

    slug = models.SlugField(
        "رابط المدرسة",
        unique=True,
        help_text="يستخدم في الرابط، مثلا: school-1",
    )

    logo = models.ImageField(
        "الشعار",
        upload_to="schools/logos/",
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(
        "اشتراك نشط",
        default=True,
        help_text="حالة تفعيل المدرسة داخل النظام (قد تكون مرتبطة بالاشتراك أو قرار إداري).",
    )

    created_at = models.DateTimeField(
    null=True,
    blank=True,
    verbose_name="تاريخ الإنشاء",
)


    class Meta:
        verbose_name = "مدرسة"
        verbose_name_plural = "المدارس"
        ordering = ("name",)
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class UserProfile(models.Model):
    """
    UserProfile (Multi-School):
    - active_school: المدرسة النشطة للمستخدم (تُستخدم في الداشبورد)
    - schools: جميع المدارس التي يمتلك المستخدم حق الوصول لها (M2M)

    ✅ توافق خلفي:
    - property اسمها school (قراءة/كتابة) = active_school
      لتفادي كسر أي كود قديم ما زال يستخدم profile.school.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="المستخدم",
    )

    active_school = models.ForeignKey(
        "core.School",
        on_delete=models.SET_NULL,
        related_name="active_profiles",
        verbose_name="المدرسة النشطة",
        null=True,
        blank=True,
        db_index=True,
    )

    schools = models.ManyToManyField(
        "core.School",
        related_name="profiles",
        verbose_name="المدارس المرتبطة",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ملف المستخدم"
        verbose_name_plural = "ملفات المستخدمين"
        indexes = [
            models.Index(fields=["active_school"]),
        ]

    def __str__(self) -> str:
        username = getattr(self.user, "username", None) or str(self.user_id)
        sc = self.active_school.name if self.active_school else "بدون مدرسة"
        return f"{username} - {sc}"

    # ---- توافق خلفي: profile.school (قراءة/كتابة) ----
    @property
    def school(self):
        return self.active_school

    @school.setter
    def school(self, value):
        self.active_school = value

    def ensure_active_school(self, commit: bool = True) -> None:
        """
        يضمن وجود active_school إذا كان لدى المستخدم مدارس مرتبطة.
        مفيد لتجنب Redirect Loop في الداشبورد.
        """
        if self.active_school_id:
            return
        first_school = self.schools.order_by("name").first()
        if first_school:
            self.active_school = first_school
            if commit:
                self.save(update_fields=["active_school"])


class DisplayScreen(models.Model):
    school = models.ForeignKey(
        "core.School",
        on_delete=models.CASCADE,
        related_name="screens",
        verbose_name="المدرسة",
        null=True,
        blank=True,
        db_index=True,
    )

    name = models.CharField(
        max_length=100,
        verbose_name="اسم الشاشة",
    )

    token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        db_index=True,
        verbose_name="رمز الوصول",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="نشط",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    last_seen = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخر ظهور",
    )

    class Meta:
        verbose_name = "شاشة عرض"
        verbose_name_plural = "شاشات العرض"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["school", "is_active"]),
            models.Index(fields=["token"]),
        ]

    def save(self, *args, **kwargs):
        if not self.token:
            # 32 bytes hex = 64 chars
            self.token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def mark_seen(self, commit: bool = True) -> None:
        """تحديث آخر ظهور (مفيد عند استدعاء snapshot)."""
        self.last_seen = timezone.now()
        if commit and self.pk:
            self.save(update_fields=["last_seen"])

    def __str__(self) -> str:
        return f"{self.school.name} - {self.name}" if self.school else self.name


class SubscriptionPlan(models.Model):
    code = models.SlugField(
        "رمز الخطة",
        unique=True,
        max_length=50,
        help_text="يُستخدم داخليًا، مثل: basic, pro, enterprise",
    )

    name = models.CharField("اسم الخطة", max_length=150)

    price_monthly = models.DecimalField(
        "السعر الشهري (ر.س)",
        max_digits=8,
        decimal_places=2,
        default=0,
    )

    max_users = models.PositiveIntegerField(
        "الحد الأقصى للمستخدمين",
        null=True,
        blank=True,
        help_text="اتركه فارغًا لعدد غير محدود.",
    )

    max_screens = models.PositiveIntegerField(
        "الحد الأقصى لشاشات العرض",
        null=True,
        blank=True,
        help_text="اتركه فارغًا لعدد غير محدود.",
    )

    is_active = models.BooleanField(
        "متاحة للاشتراك",
        default=True,
    )

    sort_order = models.PositiveIntegerField(
        "ترتيب العرض",
        default=1,
    )

    class Meta:
        verbose_name = "خطة اشتراك"
        verbose_name_plural = "خطط الاشتراك"
        ordering = ("sort_order", "price_monthly", "name")
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


# =========================
# Legacy Model (للتوافق الخلفي فقط)
# =========================

class SchoolSubscription(models.Model):
    """
    ⚠️ Legacy Model (للتوافق الخلفي فقط)

    هذا الموديل كان موجودًا سابقًا داخل core.
    الآن مصدر الحقيقة للاشتراك هو: subscriptions.SchoolSubscription

    ✅ مهم:
    - هذا الموديل لا يُحدّث School.is_active إطلاقًا (لتجنب التعارض).
    - لا تعتمد عليه في منطق صلاحيات/اشتراكات الداشبورد.
    """

    school = models.ForeignKey(
        "core.School",
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="المدرسة",
    )

    plan = models.ForeignKey(
        "core.SubscriptionPlan",
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="الخطة",
    )

    start_date = models.DateField("تاريخ البداية")

    end_date = models.DateField(
        "تاريخ الانتهاء",
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        "نشط",
        default=True,
    )

    notes = models.CharField(
        "ملاحظات",
        max_length=250,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "اشتراك مدرسة (قديم)"
        verbose_name_plural = "اشتراكات المدارس (قديمة)"
        ordering = ("-start_date", "-created_at")
        indexes = [
            models.Index(fields=["school", "is_active"]),
            models.Index(fields=["start_date"]),
        ]

    def __str__(self) -> str:
        school_name = getattr(self.school, "name", str(self.school))
        plan_name = getattr(self.plan, "name", str(self.plan))
        return f"{school_name} — {plan_name}"

    @property
    def is_expired(self) -> bool:
        if self.end_date:
            return self.end_date < timezone.localdate()
        return False

    @property
    def status(self) -> str:
        if not self.is_active:
            return "موقوف"
        if self.is_expired:
            return "منتهي"
        return "نشط"

    def save(self, *args, **kwargs):
        # ✅ لا نحدّث school.is_active هنا
        return super().save(*args, **kwargs)
