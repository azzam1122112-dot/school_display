from __future__ import annotations

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from core.models import SubscriptionPlan
from dashboard.forms import ExcellenceForm, SchoolForm, SubscriptionNewRequestForm


def _make_uploaded_noise_image(
    *,
    name: str,
    size: tuple[int, int],
    image_format: str = "JPEG",
    quality: int = 95,
) -> SimpleUploadedFile:
    image = Image.effect_noise(size, 95).convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format=image_format, quality=quality)
    content_type = f"image/{image_format.lower()}"
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class UploadOptimizationFormTests(TestCase):
    def test_school_form_logo_is_optimized_before_save(self):
        upload = _make_uploaded_noise_image(
            name="school-logo.jpg",
            size=(1800, 1800),
        )

        form = SchoolForm(
            data={"name": "مدرسة الاختبار", "slug": "school-upload-test", "is_active": "on"},
            files={"logo": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["logo"]

        self.assertEqual(getattr(cleaned, "content_type", ""), "image/webp")
        self.assertTrue(cleaned.name.endswith(".webp"))
        self.assertLess(cleaned.size, upload.size)

        cleaned.seek(0)
        with Image.open(cleaned) as image:
            self.assertLessEqual(image.width, 1200)
            self.assertLessEqual(image.height, 1200)

    def test_excellence_form_photo_is_optimized_before_save(self):
        upload = _make_uploaded_noise_image(
            name="excellence-photo.jpg",
            size=(2200, 1800),
        )
        now = timezone.localtime().replace(second=0, microsecond=0)

        form = ExcellenceForm(
            data={
                "teacher_name": "أ. سارة",
                "reason": "تميز في الأداء",
                "photo_url": "",
                "start_at": now.strftime("%Y-%m-%dT%H:%M"),
                "end_at": "",
                "priority": "1",
            },
            files={"photo": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["photo"]

        self.assertEqual(getattr(cleaned, "content_type", ""), "image/webp")
        self.assertTrue(cleaned.name.endswith(".webp"))
        self.assertLess(cleaned.size, upload.size)

        cleaned.seek(0)
        with Image.open(cleaned) as image:
            self.assertLessEqual(image.width, 1600)
            self.assertLessEqual(image.height, 1600)

    def test_subscription_receipt_image_is_optimized_before_persisting(self):
        plan = SubscriptionPlan.objects.create(
            code="upload-optimized-plan",
            name="Upload Optimized Plan",
            max_screens=3,
        )
        upload = _make_uploaded_noise_image(
            name="receipt-image.jpg",
            size=(2400, 1800),
        )

        form = SubscriptionNewRequestForm(
            data={"plan": plan.pk, "transfer_note": "إيصال اختبار"},
            files={"receipt_image": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        cleaned = form.cleaned_data["receipt_image"]

        self.assertEqual(getattr(cleaned, "content_type", ""), "image/webp")
        self.assertTrue(cleaned.name.endswith(".webp"))
        self.assertLess(cleaned.size, upload.size)

        cleaned.seek(0)
        with Image.open(cleaned) as image:
            self.assertLessEqual(image.width, 1800)
            self.assertLessEqual(image.height, 1800)
