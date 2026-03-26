from django.test import TestCase

from core.tests_utils import make_active_school_with_screen


class DashboardDisplayContractTests(TestCase):
    """
    Dashboard-facing smoke tests for the canonical display API contract.

    These tests intentionally target `/api/display/*` directly to ensure
    the dashboard ecosystem remains aligned with the current source of truth.
    """

    def test_status_accepts_path_token(self):
        bundle = make_active_school_with_screen(max_screens=3)
        resp = self.client.get(f"/api/display/status/{bundle.screen.token}/?v=0")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("fetch_required", payload)
        self.assertIn("schedule_revision", payload)

    def test_snapshot_requires_device_key(self):
        bundle = make_active_school_with_screen(max_screens=3)
        resp = self.client.get(f"/api/display/snapshot/{bundle.screen.token}/")
        self.assertEqual(resp.status_code, 403)

    def test_snapshot_with_device_key_is_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        resp = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "dashboard-smoke-dev"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn("settings", payload)
        self.assertIn("state", payload)
        self.assertIn("period_classes", payload)

    def test_snapshot_aliases_stay_wired(self):
        bundle = make_active_school_with_screen(max_screens=3)
        token = bundle.screen.token
        today_resp = self.client.get(f"/api/display/today/?token={token}")
        live_resp = self.client.get(f"/api/display/live/?token={token}")
        self.assertEqual(today_resp.status_code, 200)
        self.assertEqual(live_resp.status_code, 200)
