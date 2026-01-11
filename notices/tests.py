from django.test import TestCase
from core.models import School, DisplayScreen

from core.tests_utils import make_active_school_with_screen


class NoticesAPITests(TestCase):
    def test_active_announcements_empty_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)

        resp = self.client.get(f"/api/announcements/active/?token={bundle.screen.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["items"], [])

from django.test import TestCase

class AnnouncementsSecurityTests(TestCase):
    def test_active_requires_auth_or_token(self):
        r = self.client.get("/api/announcements/active/")
        self.assertEqual(r.status_code, 403)


from django.test import TestCase


class AnnouncementsApiSecurityTests(TestCase):
    def test_active_requires_display_token(self):
        r = self.client.get("/api/announcements/active/")
        self.assertEqual(r.status_code, 403)

    def test_excellence_requires_display_token(self):
        r = self.client.get("/api/announcements/excellence/")
        self.assertEqual(r.status_code, 403)


from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import School, DisplayScreen
from notices.models import Announcement, Excellence


class AnnouncementsApiSuccessTests(TestCase):
    def setUp(self):
        bundle = make_active_school_with_screen(max_screens=3)
        self.school = bundle.school
        self.screen = bundle.screen

        self.now = timezone.now()

    def test_active_announcements_ok_with_token(self):
        Announcement.objects.create(
            school=self.school,
            title="تنبيه 1",
            body="نص",
            level="info",
            starts_at=self.now - timedelta(minutes=5),
            expires_at=None,
            is_active=True,
        )

        r = self.client.get(f"/api/announcements/active/?token={self.screen.token}")
        self.assertEqual(r.status_code, 200)

        data = r.json()
        self.assertIn("items", data)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["title"], "تنبيه 1")

    def test_active_excellence_ok_with_token(self):
        Excellence.objects.create(
            school=self.school,
            teacher_name="أ. أحمد",
            reason="متميز الأسبوع",
            photo=None,
            photo_url="https://example.com/photo.jpg",
            start_at=self.now - timedelta(minutes=5),
            end_at=None,
            priority=1,
        )

        r = self.client.get(f"/api/announcements/excellence/?token={self.screen.token}")
        self.assertEqual(r.status_code, 200)

        data = r.json()
        self.assertIn("items", data)
        self.assertEqual(len(data["items"]), 1)
        # حسب الـSerializer عندك قد يكون المفتاح teacher_name أو name… نتحقق من وجود أحدهما
        item = data["items"][0]
        self.assertTrue(item.get("teacher_name") == "أ. أحمد" or item.get("name") == "أ. أحمد")

    def test_active_announcements_ok_with_header_token(self):
        Announcement.objects.create(
            school=self.school,
            title="تنبيه Header",
            body="نص",
            level="info",
            starts_at=self.now - timedelta(minutes=5),
            expires_at=None,
            is_active=True,
        )

        r = self.client.get(
            "/api/announcements/active/",
            HTTP_X_DISPLAY_TOKEN=self.screen.token,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json().get("items", [])), 1)
