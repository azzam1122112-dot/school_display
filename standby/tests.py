from django.test import TestCase

from core.tests_utils import make_active_school_with_screen


class StandbyAPITests(TestCase):
    def test_today_standby_empty_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)

        resp = self.client.get(f"/api/standby/today/?token={bundle.screen.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())
