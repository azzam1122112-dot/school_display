from django.test import TestCase
from django.conf import settings as dj_settings
from django.core.cache import cache
from django.utils import timezone

from core.tests_utils import make_active_school_with_screen

class DisplayApiAliasesTests(TestCase):
    def test_snapshot_requires_device_key_is_403(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/snapshot/{bundle.screen.token}/")
        self.assertEqual(r.status_code, 403)

    def test_snapshot_ok_with_query_device_key(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/?dk=devA",
        )
        self.assertEqual(r.status_code, 200)

    def test_snapshot_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.get("Cache-Control"), "no-store")
        self.assertTrue(r.get("ETag"))

        vary = (r.get("Vary") or "")
        self.assertNotIn("Cookie", vary)
        self.assertIn("Accept-Encoding", vary)
        self.assertFalse(bool(r.cookies))
        self.assertIsNone(r.get("Set-Cookie"))

    def test_snapshot_nocache_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/?nocache=1",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(r.status_code, 200)

        self.assertEqual(r.get("Cache-Control"), "no-store")
        self.assertTrue(r.get("ETag"))
        vary = (r.get("Vary") or "")
        self.assertNotIn("Cookie", vary)
        self.assertIn("Accept-Encoding", vary)
        self.assertFalse(bool(r.cookies))
        self.assertIsNone(r.get("Set-Cookie"))

    def test_snapshot_etag_304(self):
        bundle = make_active_school_with_screen(max_screens=3)
        url = f"/api/display/snapshot/{bundle.screen.token}/"

        r1 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r1.status_code, 200)
        etag = r1.get("ETag")
        self.assertTrue(etag)

        r2 = self.client.get(url, **{"HTTP_IF_NONE_MATCH": etag, "HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r2.status_code, 304)
        self.assertEqual(r2.get("ETag"), etag)
        self.assertEqual(r2.get("Cache-Control"), "no-store")

    def test_snapshot_rate_limit(self):
        bundle = make_active_school_with_screen(max_screens=3)
        url = f"/api/display/snapshot/{bundle.screen.token}/"

        # Burst is 3; the 4th should be rate-limited.
        for _ in range(3):
            r = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
            self.assertIn(r.status_code, {200, 304})

        r4 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r4.status_code, 429)
        self.assertEqual(r4.get("Cache-Control"), "no-store")

    def test_snapshot_device_binding_header(self):
        bundle = make_active_school_with_screen(max_screens=3)
        url = f"/api/display/snapshot/{bundle.screen.token}/"

        r1 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devB"})
        self.assertEqual(r2.status_code, 403)
        try:
            body = r2.json()
        except Exception:
            body = {}
        self.assertIn(body.get("detail"), {"device_mismatch", "screen_bound", None})

    def test_today_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/today/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)

    def test_live_alias_ok(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.get(f"/api/display/live/?token={bundle.screen.token}")
        self.assertEqual(r.status_code, 200)


class DisplaySnapshotPhase2Tests(TestCase):
    def test_snapshot_isolation_between_schools(self):
        cache.clear()
        a = make_active_school_with_screen(max_screens=3)
        b = make_active_school_with_screen(max_screens=3)

        ra = self.client.get(
            f"/api/display/snapshot/{a.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(ra.status_code, 200)
        ja = ra.json()

        rb = self.client.get(
            f"/api/display/snapshot/{b.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devB"},
        )
        self.assertEqual(rb.status_code, 200)
        jb = rb.json()

        self.assertNotEqual(a.school.id, b.school.id)
        self.assertIn("settings", ja)
        self.assertIn("settings", jb)
        self.assertIn((a.settings.name if a.settings else ""), (ja.get("settings") or {}).get("name") or "")
        self.assertIn((b.settings.name if b.settings else ""), (jb.get("settings") or {}).get("name") or "")
        self.assertNotIn((b.settings.name if b.settings else ""), (ja.get("settings") or {}).get("name") or "")
        self.assertNotIn((a.settings.name if a.settings else ""), (jb.get("settings") or {}).get("name") or "")

    def test_steady_snapshot_no_schedule_has_safe_payload_and_cached(self):
        bundle = make_active_school_with_screen(max_screens=3)
        cache.clear()

        url = f"/api/display/snapshot/{bundle.screen.token}/"
        r1 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r1.status_code, 200)
        body = r1.json()

        st = body.get("state") or {}
        self.assertEqual(st.get("type"), "NO_SCHEDULE_TODAY")

        settings = body.get("settings") or {}
        self.assertGreaterEqual(int(settings.get("refresh_interval_sec") or 0), 3600)

        # UI-safe arrays
        self.assertIsInstance(body.get("announcements"), list)
        self.assertIsInstance(body.get("standby"), list)
        self.assertIsInstance(body.get("excellence"), list)
        self.assertIsInstance(body.get("period_classes"), list)

        # Ensure steady cache is written (school-scoped and date-scoped)
        today = str(timezone.localdate())
        steady_key = f"snapshot:v2:school:{bundle.school.id}:steady:{today}"
        cached = cache.get(steady_key)
        self.assertIsInstance(cached, dict)

        # Second request should be served from cache (200 or 304)
        r2 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA", "HTTP_IF_NONE_MATCH": r1.get("ETag")})
        self.assertIn(r2.status_code, {200, 304})
