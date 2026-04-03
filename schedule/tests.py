from datetime import datetime, time
from unittest import mock
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.conf import settings as dj_settings
from django.core.cache import cache
from django.utils import timezone

from core.tests_utils import make_active_school_with_screen
from schedule.cache_utils import set_cached_schedule_revision_for_school_id


def _assert_snapshot_cache_control(resp) -> None:
    cc = (resp.get("Cache-Control") or "").strip().lower()
    # Successful snapshot responses intentionally allow small edge caching while
    # forcing browsers to revalidate.
    # Examples: "public, max-age=0, must-revalidate, s-maxage=10"
    if resp.status_code in (200, 304):
        assert "max-age=0" in cc, cc
        assert "must-revalidate" in cc, cc
        assert "s-maxage" in cc, cc
        return
    # Errors should remain no-store.
    assert cc == "no-store", cc

class DisplayApiAliasesTests(TestCase):
    def test_snapshot_head_ok_with_query_device_key(self):
        bundle = make_active_school_with_screen(max_screens=3)
        r = self.client.head(
            f"/api/display/snapshot/{bundle.screen.token}/?dk=devA",
        )
        self.assertIn(r.status_code, {200, 304})

    def test_status_head_ok_revision_mode(self):
        bundle = make_active_school_with_screen(max_screens=3)

        # Prime token->school map cache via snapshot.
        r1 = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(r1.status_code, 200)

        # Use current revision to trigger 304.
        if bundle.settings:
            try:
                bundle.settings.refresh_from_db()
            except Exception:
                pass
        cur_rev = int(getattr(bundle.settings, "schedule_revision", 0) or 0)

        r2 = self.client.head(
            f"/api/display/status/{bundle.screen.token}/?v={cur_rev}",
        )
        self.assertEqual(r2.status_code, 304)

    def test_status_steady_state_is_zero_db_queries(self):
        bundle = make_active_school_with_screen(max_screens=3)

        # Prime device binding + token->school cache through snapshot once.
        snapshot_resp = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(snapshot_resp.status_code, 200)

        if bundle.settings:
            try:
                bundle.settings.refresh_from_db()
            except Exception:
                pass
        cur_rev = int(getattr(bundle.settings, "schedule_revision", 0) or 0)
        set_cached_schedule_revision_for_school_id(bundle.school.id, cur_rev)

        with mock.patch("schedule.api_views._cache_is_shared", return_value=True):
            with CaptureQueriesContext(connection) as ctx:
                status_resp = self.client.get(
                    f"/api/display/status/{bundle.screen.token}/?v={cur_rev}",
                    **{"HTTP_X_DISPLAY_DEVICE": "devA"},
                )

        self.assertEqual(status_resp.status_code, 304)
        self.assertEqual(
            len(ctx.captured_queries),
            0,
            msg=f"expected 0 DB queries in /status steady state, saw {len(ctx.captured_queries)}",
        )

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

        _assert_snapshot_cache_control(r)
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

        _assert_snapshot_cache_control(r)
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
        _assert_snapshot_cache_control(r2)

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

    def test_status_device_binding_rejects_other_device(self):
        bundle = make_active_school_with_screen(max_screens=3)
        snapshot_url = f"/api/display/snapshot/{bundle.screen.token}/"
        status_url = f"/api/display/status/{bundle.screen.token}/?v=0"

        r1 = self.client.get(snapshot_url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.get(status_url, **{"HTTP_X_DISPLAY_DEVICE": "devB"})
        self.assertEqual(r2.status_code, 403)
        self.assertEqual(r2.json().get("detail"), "screen_bound")

    def test_snapshot_blank_bound_device_is_treated_as_unbound(self):
        bundle = make_active_school_with_screen(max_screens=3)
        bundle.screen.bound_device_id = ""
        bundle.screen.bound_at = None
        bundle.screen.save(update_fields=["bound_device_id", "bound_at"])

        resp = self.client.get(
            f"/api/display/snapshot/{bundle.screen.token}/",
            **{"HTTP_X_DISPLAY_DEVICE": "devA"},
        )
        self.assertEqual(resp.status_code, 200)

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

        # Ensure steady cache is written (use the same key builder as production)
        from schedule.api_views import _steady_snapshot_cache_key
        if bundle.settings:
            try:
                bundle.settings.refresh_from_db()
            except Exception:
                pass
        steady_key = _steady_snapshot_cache_key(bundle.settings, body)
        cached = cache.get(steady_key)
        self.assertIsInstance(cached, dict)

        # Second request should be served from cache (200 or 304)
        r2 = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA", "HTTP_IF_NONE_MATCH": r1.get("ETag")})
        self.assertIn(r2.status_code, {200, 304})

    def test_materialize_snapshot_for_school_writes_shared_artifact(self):
        bundle = make_active_school_with_screen(max_screens=3)
        cache.clear()

        if bundle.settings:
            try:
                bundle.settings.refresh_from_db()
            except Exception:
                pass
        rev = int(getattr(bundle.settings, "schedule_revision", 0) or 0)

        from schedule.api_views import _snapshot_cache_entry_from_cached, _steady_cache_key_for_school_rev
        from schedule.snapshot_materializer import materialize_snapshot_for_school

        result = materialize_snapshot_for_school(
            school_id=bundle.school.id,
            rev=rev,
            day_key=timezone.localdate().isoformat(),
            source="test",
        )
        self.assertTrue(result.get("ok"), msg=str(result))

        steady_key = _steady_cache_key_for_school_rev(bundle.school.id, int(result.get("built_rev") or rev), day_key=timezone.localdate().isoformat())
        entry = _snapshot_cache_entry_from_cached(cache.get(steady_key))
        self.assertIsInstance(entry, dict)
        self.assertEqual((entry.get("snap") or {}).get("meta", {}).get("materialized"), True)

    def test_get_or_build_snapshot_can_return_queued_building_payload(self):
        cache.clear()

        from schedule.api_views import get_or_build_snapshot

        with mock.patch("schedule.snapshot_materializer.snapshot_async_build_enabled", return_value=True), \
             mock.patch("schedule.snapshot_materializer.snapshot_queue_available", return_value=True), \
             mock.patch("schedule.snapshot_materializer.snapshot_worker_status", return_value={"alive": True, "queue_available": True}), \
             mock.patch("schedule.snapshot_materializer.snapshot_inline_fallback_enabled", return_value=False), \
             mock.patch("schedule.snapshot_materializer.enqueue_snapshot_build") as enqueue_mock, \
             mock.patch("schedule.snapshot_materializer.wait_for_materialized_snapshot", return_value=None), \
             mock.patch("schedule.api_views._get_stale_snapshot_fallback", return_value=None):
            entry, cache_kind = get_or_build_snapshot(
                999,
                77,
                mock.Mock(side_effect=AssertionError("builder should not run inline")),
                day_key="2026-04-03",
            )

        self.assertEqual(cache_kind, "QUEUED")
        self.assertEqual(((entry.get("snap") or {}).get("state") or {}).get("type"), "BUILDING")
        enqueue_mock.assert_called_once()


class SnapshotTtlHelpersTests(TestCase):
    @override_settings(DISPLAY_SNAPSHOT_ACTIVE_TTL=15, DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX=60)
    def test_active_ttl_lifts_to_refresh_interval(self):
        from schedule.api_views import _active_snapshot_cache_ttl_seconds

        snap = {
            "settings": {"refresh_interval_sec": 20},
            "meta": {"is_active_window": True},
            "state": {"type": "period", "remaining_seconds": 1800},
        }
        ttl = _active_snapshot_cache_ttl_seconds(snap)
        self.assertGreaterEqual(ttl, 20)

    @override_settings(
        DISPLAY_SNAPSHOT_ACTIVE_TTL=15,
        DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX=60,
        DISPLAY_SNAPSHOT_ACTIVE_STEADY_TTL=120,
    )
    def test_active_fallback_ttl_is_clamped_by_remaining_seconds(self):
        from schedule.api_views import _active_fallback_steady_ttl_seconds

        snap = {
            "settings": {"refresh_interval_sec": 20},
            "meta": {"is_active_window": True},
            "state": {"type": "period", "remaining_seconds": 12},
        }
        ttl = _active_fallback_steady_ttl_seconds(snap)
        self.assertEqual(ttl, 15)

    def test_steady_cache_key_varies_by_snapshot_date(self):
        from schedule.api_views import _steady_snapshot_cache_key

        bundle = make_active_school_with_screen(max_screens=3)
        self.assertIsNotNone(bundle.settings)

        key_a = _steady_snapshot_cache_key(bundle.settings, {"meta": {"date": "2026-04-01"}})
        key_b = _steady_snapshot_cache_key(bundle.settings, {"meta": {"date": "2026-04-02"}})

        self.assertNotEqual(key_a, key_b)
        self.assertIn("day:2026-04-01", key_a)
        self.assertIn("day:2026-04-02", key_b)

    def test_steady_cache_stores_precomputed_body_and_etag(self):
        from schedule.api_views import _steady_snapshot_cache_key

        bundle = make_active_school_with_screen(max_screens=3)
        url = f"/api/display/snapshot/{bundle.screen.token}/"

        resp = self.client.get(url, **{"HTTP_X_DISPLAY_DEVICE": "devA"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        if bundle.settings:
            try:
                bundle.settings.refresh_from_db()
            except Exception:
                pass
        steady_key = _steady_snapshot_cache_key(bundle.settings, body)
        cached = cache.get(steady_key)

        self.assertIsInstance(cached, dict)
        self.assertIsInstance(cached.get("snap"), dict)
        self.assertIsInstance(cached.get("etag"), str)
        self.assertTrue(cached.get("etag"))
        self.assertIsInstance(cached.get("body"), (bytes, bytearray))
        self.assertGreater(len(cached.get("body") or b""), 0)


class BuildDaySnapshotTimingTests(TestCase):
    def test_build_day_snapshot_preserves_precise_timing_metadata_for_local_transitions(self):
        from schedule.models import Break, DaySchedule, Period, SchoolClass, Subject, Teacher
        from schedule.time_engine import build_day_snapshot

        bundle = make_active_school_with_screen(max_screens=3)
        self.assertIsNotNone(bundle.settings)

        settings = bundle.settings
        settings.timezone_name = "Asia/Riyadh"
        settings.save(update_fields=["timezone_name"])

        tz = ZoneInfo("Asia/Riyadh")
        before_start = datetime(2026, 3, 29, 7, 55, tzinfo=tz)

        school_class = SchoolClass.objects.create(settings=settings, name="1/أ")
        teacher = Teacher.objects.create(school=bundle.school, name="أ. أحمد")
        math = Subject.objects.create(school=bundle.school, name="رياضيات")
        science = Subject.objects.create(school=bundle.school, name="علوم")

        day = DaySchedule.objects.create(
            settings=settings,
            weekday=before_start.weekday() + 1,
            is_active=True,
            periods_count=2,
        )
        Period.objects.create(
            day=day,
            school_class=school_class,
            subject=math,
            teacher=teacher,
            index=1,
            starts_at=time(8, 0),
            ends_at=time(8, 30),
        )
        Break.objects.create(
            day=day,
            label="فسحة الصباح",
            starts_at=time(8, 30),
            duration_min=10,
        )
        Period.objects.create(
            day=day,
            school_class=school_class,
            subject=science,
            teacher=teacher,
            index=2,
            starts_at=time(8, 40),
            ends_at=time(9, 10),
        )

        before = build_day_snapshot(settings, now=before_start)
        self.assertTrue(before["now"].endswith("+03:00"))
        self.assertEqual(before["state"]["type"], "before")
        self.assertEqual(before["state"]["remaining_seconds"], 5 * 60)
        self.assertEqual(before["next_period"]["index"], 1)
        self.assertEqual(before["day_path"][0]["index"], 1)
        self.assertEqual(before["day_path"][0]["label"], "رياضيات")
        self.assertEqual(before["day_path"][0]["class"], "1/أ")
        self.assertEqual(before["day_path"][0]["teacher"], "أ. أحمد")

        first_period = build_day_snapshot(settings, now=datetime(2026, 3, 29, 8, 10, tzinfo=tz))
        self.assertEqual(first_period["state"]["type"], "period")
        self.assertEqual(first_period["state"]["period_index"], 1)
        self.assertEqual(first_period["state"]["remaining_seconds"], 20 * 60)
        self.assertEqual(first_period["current_period"]["label"], "رياضيات")
        self.assertEqual(first_period["current_period"]["class"], "1/أ")
        self.assertEqual(first_period["current_period"]["remaining_seconds"], 20 * 60)
        self.assertEqual(first_period["next_period"]["kind"], "break")
        self.assertEqual(first_period["next_period"]["label"], "فسحة الصباح")

        break_time = build_day_snapshot(settings, now=datetime(2026, 3, 29, 8, 35, tzinfo=tz))
        self.assertEqual(break_time["state"]["type"], "break")
        self.assertEqual(break_time["state"]["label"], "فسحة الصباح")
        self.assertEqual(break_time["state"]["remaining_seconds"], 5 * 60)
        self.assertEqual(break_time["current_period"]["label"], "فسحة الصباح")
        self.assertEqual(break_time["next_period"]["index"], 2)
        self.assertEqual(break_time["next_period"]["label"], "علوم")

        after = build_day_snapshot(settings, now=datetime(2026, 3, 29, 9, 10, tzinfo=tz))
        self.assertEqual(after["state"]["type"], "after")
        self.assertEqual(after["state"]["remaining_seconds"], 0)
