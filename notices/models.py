# notices/models.py
from __future__ import annotations
import os
import uuid
from datetime import datetime

from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator

ANNOUNCEMENT_LEVELS = (
    ("urgent", "عاجل"),
    ("warning", "تنبيه"),
    ("info", "معلومة"),
    ("success", "تهنئة"),
)

def _excellence_upload_to(instance: "Excellence", filename: str) -> str:
    """
    مسار رفع الصورة: excellence/YYYY/MM/<uuid4><ext>
    يحافظ على الامتداد الأصلي، ويضمن اسمًا فريدًا.
    """
    _, ext = os.path.splitext(filename)
    ext = (ext or "").lower()[:10]  # تنقية بسيطة
    now = datetime.now()
    return f"excellence/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext or '.jpg'}"


class Announcement(models.Model):
    title = models.CharField("العنوان", max_length=120)
    body = models.CharField("النص", max_length=280, blank=True)
    level = models.CharField("المستوى", max_length=10, choices=ANNOUNCEMENT_LEVELS, default="info")
    starts_at = models.DateTimeField("يظهر من", default=timezone.now)
    expires_at = models.DateTimeField("ينتهي في", blank=True, null=True)
    is_active = models.BooleanField("مفعّل", default=True)

    class Meta:
        verbose_name = "تنبيه"
        verbose_name_plural = "تنبيهات"
        ordering = ("-starts_at",)

    def __str__(self) -> str:
        return f"[{self.get_level_display()}] {self.title}"

    @property
    def active_now(self) -> bool:
        if not self.is_active:
            return False
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.expires_at and now >= self.expires_at:
            return False
        return True


class Excellence(models.Model):
    teacher_name = models.CharField("اسم المعلم", max_length=100)
    reason = models.CharField("سبب التميّز", max_length=200)

    # ✅ خيار 1: رفع صورة ملف (مستحسن)
    photo = models.ImageField(
        "صورة (رفع ملف)",
        upload_to=_excellence_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
        help_text="صيغة مدعومة: JPG/PNG/WEBP. الحجم يُدار عبر إعدادات الخادم.",
    )

    # ✅ خيار 2: عنوان صورة عن طريق رابط (اختياري كبديل)
    photo_url = models.URLField("رابط صورة (اختياري)", blank=True, null=True)

    start_at = models.DateTimeField("يظهر من", default=timezone.now)
    end_at = models.DateTimeField("ينتهي في", blank=True, null=True)
    priority = models.PositiveSmallIntegerField("أولوية العرض", default=10)

    class Meta:
        verbose_name = "تميّز"
        verbose_name_plural = "تميّز"
        ordering = ("priority", "-start_at")

    def __str__(self) -> str:
        return f"{self.teacher_name} — {self.reason}"

    @property
    def active_now(self) -> bool:
        now = timezone.now()
        if self.start_at and now < self.start_at:
            return False
        if self.end_at and now >= self.end_at:
            return False
        return True

    @property
    def image_src(self) -> str | None:
        """
        يرجع رابط الصورة المعتمدة للعرض:
        - إذا كان هناك ملف مرفوع -> self.photo.url
        - وإلا إن وُجِد photo_url -> يعاد كما هو
        - وإلا None
        """
        try:
            if self.photo and hasattr(self.photo, "url"):
                return self.photo.url
        except ValueError:
            # في حال الملف غير متوفر على التخزين
            pass
        return self.photo_url or None

    def save(self, *args, **kwargs):
        """
        تنظيف بسيط: عند استبدال صورة مرفوعة بصورة جديدة، احذف القديمة من التخزين.
        """
        old_path = None
        if self.pk:
            try:
                old = Excellence.objects.get(pk=self.pk)
                if old.photo and self.photo and old.photo.name != self.photo.name:
                    old_path = old.photo.path
            except Excellence.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        # احذف الملف القديم بعد نجاح الحفظ (إن وُجد ومختلف)
        if old_path and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                # لا توقف الحفظ بسبب خطأ حذف ملف
                pass
