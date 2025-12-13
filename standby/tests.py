from django.test import TestCase
from core.models import School, DisplayScreen


class StandbyAPITests(TestCase):
    def test_today_standby_empty_ok(self):
        school = School.objects.create(name="Test School", slug="test-school")
        screen = DisplayScreen.objects.create(school=school, name="Screen 1")

        resp = self.client.get(f"/api/standby/today/?token={screen.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())
