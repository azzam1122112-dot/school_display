from django.test import TestCase

class DisplayApiAliasesTests(TestCase):
    def test_snapshot_ok(self):
        r = self.client.get("/api/display/snapshot/")
        self.assertEqual(r.status_code, 200)

    def test_today_alias_ok(self):
        r = self.client.get("/api/display/today/")
        self.assertEqual(r.status_code, 200)

    def test_live_alias_ok(self):
        r = self.client.get("/api/display/live/")
        self.assertEqual(r.status_code, 200)
