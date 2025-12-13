from django.test import TestCase
from core.models import School, DisplayScreen


class ValidateDisplayTokenTests(TestCase):
    def test_validate_token_via_api_announcements(self):
        school = School.objects.create(name="Test School", slug="test-school")
        screen = DisplayScreen.objects.create(school=school, name="Screen 1")

        resp = self.client.get(f"/api/announcements/active/?token={screen.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())

    def test_forbidden_without_token(self):
        resp = self.client.get("/api/announcements/active/")
        self.assertEqual(resp.status_code, 403)
