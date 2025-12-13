from datetime import date

from django.db import models
from django.utils import timezone

from core.models import School, SubscriptionPlan


class SchoolSubscription(models.Model):
    STATUS_CHOICES = [
        ("pending", "قيد الإعداد"),
        ("active", "سارية"),
        ("expired", "منتهية"),
        ("cancelled", "ملغاة"),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name="المدرسة",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name="الخطة",
    )
    starts_at = models.DateField(
        default=timezone.localdate,
        verbose_name="بداية الاشتراك",
    )
    ends_at = models.DateField(
        null=True,
        blank=True,
        verbose_name="نهاية الاشتراك",
        help_text="اتركه فارغًا ليكون مفتوح المدة.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
        verbose_name="الحالة",
    )
    notes = models.TextField(
        blank=True,
        verbose_name="ملاحظات",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاريخ الإنشاء",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="آخر تحديث",
    )

    class Meta:
        verbose_name = "اشتراك مدرسة"
        verbose_name_plural = "اشتراكات المدارس"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["school", "plan", "starts_at"],
                name="uniq_school_plan_start",
            )
        ]

    def __str__(self) -> str:
        return f"{self.school} - {self.plan} ({self.starts_at})"

    @property
    def is_active(self) -> bool:
        """
        هل الاشتراك ساري المفعول حاليًا؟
        يعتمد على الحالة والتاريخ.
        """
        today = timezone.localdate()

        if self.status != "active":
            return False

        if self.ends_at and self.ends_at < today:
            return False

        return True

    @property
    def days_left(self):
        """
        عدد الأيام المتبقية حتى انتهاء الاشتراك.
        يرجع None إذا كان الاشتراك مفتوح المدة (بدون تاريخ انتهاء).
        """
        if not self.ends_at:
            return None  # اشتراك مفتوح المدة

        today = date.today()
        delta = (self.ends_at - today).days
        return delta if delta >= 0 else 0
