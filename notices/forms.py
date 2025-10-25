# notices/forms.py
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Announcement, Excellence


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "level", "starts_at", "expires_at", "is_active"]
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 120, "class": "w-full"}),
            "body": forms.Textarea(
                attrs={"rows": 3, "maxlength": 280, "class": "w-full"}
            ),
            # HTML5 datetime-local يتوقع قيمة بدون timezone; اترك التحويل لمنطق العرض/المسلسل
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get("starts_at")
        expires_at = cleaned.get("expires_at")
        if starts_at and expires_at and expires_at <= starts_at:
            raise ValidationError(_("وقت الانتهاء يجب أن يكون بعد وقت البداية."))
        return cleaned


class ExcellenceForm(forms.ModelForm):
    """
    يدعم:
      - رفع صورة (ImageField: photo)
      - أو رابط صورة (photo_url)
    الأولوية للملف المرفوع عند العرض عبر خاصية model.image_src.
    """

    MAX_PHOTO_MB = 5  # حد حجم افتراضي (يمكن تعديله)

    class Meta:
        model = Excellence
        fields = [
            "teacher_name",
            "reason",
            "photo",       # ← جديد: رفع ملف
            "photo_url",   # ← رابط صورة (اختياري)
            "start_at",
            "end_at",
            "priority",
        ]
        widgets = {
            "teacher_name": forms.TextInput(attrs={"maxlength": 100, "class": "w-full"}),
            "reason": forms.TextInput(attrs={"maxlength": 200, "class": "w-full"}),
            "start_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean_photo(self):
        file = self.cleaned_data.get("photo")
        if not file:
            return file
        # تحقق من الحجم تقريبًا (الأمان الحقيقي يكون عبر إعدادات الخادم / Nginx)
        max_bytes = self.MAX_PHOTO_MB * 1024 * 1024
        if getattr(file, "size", 0) > max_bytes:
            raise ValidationError(
                _("حجم الصورة يتجاوز %(mb)s م.ب."),
                params={"mb": self.MAX_PHOTO_MB},
            )
        return file

    def clean(self):
        cleaned = super().clean()
        start_at = cleaned.get("start_at")
        end_at = cleaned.get("end_at")
        if start_at and end_at and end_at <= start_at:
            raise ValidationError(_("وقت الانتهاء يجب أن يكون بعد وقت البداية."))
        return cleaned
