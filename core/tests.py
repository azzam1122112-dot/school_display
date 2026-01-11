from django.test import TestCase

from core.tests_utils import make_active_school_with_screen


class ValidateDisplayTokenTests(TestCase):
    def test_validate_token_via_api_announcements(self):
        bundle = make_active_school_with_screen(max_screens=3)

        resp = self.client.get(f"/api/announcements/active/?token={bundle.screen.token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())

    def test_forbidden_without_token(self):
        resp = self.client.get("/api/announcements/active/")
        self.assertEqual(resp.status_code, 403)
