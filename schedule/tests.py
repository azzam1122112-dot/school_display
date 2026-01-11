from django.test import TestCase

from core.tests_utils import make_active_school_with_screen

class DisplayApiAliasesTests(TestCase):
    def test_snapshot_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/snapshot/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)

    def test_today_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/today/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)

    def test_live_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/live/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)
