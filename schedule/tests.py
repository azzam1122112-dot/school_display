from django.test import TestCase
from django.conf import settings as dj_settings

from core.tests_utils import make_active_school_with_screen

class DisplayApiAliasesTests(TestCase):
    def test_snapshot_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/snapshot/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)

        edge_ttl = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_EDGE_MAX_AGE", 10) or 10)
        expected_cc = f"public, max-age=0, s-maxage={edge_ttl}"
        self.assertEqual(r.get("Cache-Control"), expected_cc)

        vary = (r.get("Vary") or "")
        self.assertNotIn("Cookie", vary)
        self.assertNotIn("Accept-Encoding", vary)
        self.assertFalse(bool(r.cookies))
        self.assertIsNone(r.get("Set-Cookie"))

    def test_snapshot_nocache_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/snapshot/?token={bundle.screen.token}&nocache=1")
        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.get("Cache-Control"), "no-store")
        vary = (r.get("Vary") or "")
        self.assertNotIn("Cookie", vary)
        self.assertNotIn("Accept-Encoding", vary)
        self.assertFalse(bool(r.cookies))
        self.assertIsNone(r.get("Set-Cookie"))

    def test_today_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/today/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)

    def test_live_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/live/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)
