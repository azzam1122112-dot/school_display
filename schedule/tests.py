from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from schedule import api_views as av
from schedule import snapshot_materializer as sm
from schedule import snapshot_observability as so


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def get(self, key):
        return self.store.get(str(key))

    def set(self, key, value, nx=False, ex=None):
        key = str(key)
        if nx and key in self.store:
            return False
        self.store[key] = str(value)
        return True

    def delete(self, key):
        return int(self.store.pop(str(key), None) is not None)

    def expire(self, key, ttl):
        return bool(str(key) in self.store)

    def rpush(self, key, value):
        self.lists.setdefault(str(key), []).append(value)
        return len(self.lists[str(key)])

    def blpop(self, key, timeout=0):
        items = self.lists.setdefault(str(key), [])
        if not items:
            return None
        return str(key), items.pop(0)

    def llen(self, key):
        return len(self.lists.get(str(key), []))

    def eval(self, script, numkeys, key, *args):
        raise NotImplementedError


@override_settings(
    DISPLAY_SNAPSHOT_ASYNC_BUILD=True,
    DISPLAY_SNAPSHOT_REQUIRE_WORKER_ALIVE=False,
    DISPLAY_SNAPSHOT_DEBOUNCE_SEC=0,
    DISPLAY_SNAPSHOT_PENDING_TTL_SEC=30,
    DISPLAY_SNAPSHOT_LATEST_REV_TTL_SEC=120,
)
class SnapshotQueueCoalescingTests(SimpleTestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.patches = [
            patch.object(sm, "_get_queue_redis_connection", return_value=self.redis),
            patch.object(sm, "snapshot_queue_available", return_value=True),
            patch.object(sm, "_metrics_incr", lambda *args, **kwargs: None),
            patch.object(sm, "_metrics_add", lambda *args, **kwargs: None),
            patch.object(sm, "_metrics_set_max", lambda *args, **kwargs: None),
            patch.object(sm, "_obs_snapshot_queue", lambda *args, **kwargs: None),
            patch.object(sm, "_obs_snapshot_build", lambda *args, **kwargs: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_rapid_triggers_keep_one_pending_job_and_latest_revision(self):
        first = sm.enqueue_snapshot_build(school_id=1, rev=1080, day_key="2026-04-20")
        second = sm.enqueue_snapshot_build(school_id=1, rev=1081, day_key="2026-04-20")
        third = sm.enqueue_snapshot_build(school_id=1, rev=1082, day_key="2026-04-20")

        self.assertTrue(first["queued"])
        self.assertTrue(second["duplicate"])
        self.assertTrue(third["duplicate"])
        self.assertEqual(self.redis.llen(sm._queue_name()), 1)
        self.assertEqual(self.redis.get(sm._latest_rev_key(1, "2026-04-20")), "1082")

    def test_dequeue_coalesces_old_job_to_latest_revision(self):
        sm.enqueue_snapshot_build(school_id=1, rev=1080, day_key="2026-04-20")
        sm.enqueue_snapshot_build(school_id=1, rev=1083, day_key="2026-04-20")

        job = sm.dequeue_snapshot_build(block_timeout=0)

        self.assertIsNotNone(job)
        self.assertEqual(job["rev"], 1083)
        self.assertEqual(job["_coalesced_from_rev"], 1080)

    @override_settings(DISPLAY_SNAPSHOT_DEBOUNCE_SEC=3)
    def test_enqueue_debounce_skips_second_job_but_updates_latest_revision(self):
        first = sm.enqueue_snapshot_build(school_id=1, rev=1080, day_key="2026-04-20")
        second = sm.enqueue_snapshot_build(school_id=1, rev=1081, day_key="2026-04-20")

        self.assertTrue(first["queued"])
        self.assertEqual(first["reason"], "queued")
        self.assertFalse(first["debounced"])
        self.assertFalse(first["deduped"])
        self.assertFalse(first["coalesced"])
        self.assertFalse(second["queued"])
        self.assertEqual(second["reason"], "debounced")
        self.assertTrue(second["debounced"])
        self.assertFalse(second["deduped"])
        self.assertTrue(second["coalesced"])
        self.assertEqual(self.redis.llen(sm._queue_name()), 1)
        self.assertEqual(self.redis.get(sm._latest_rev_key(1, "2026-04-20")), "1081")

    def test_already_materialized_latest_job_is_marked_skippable(self):
        sm.enqueue_snapshot_build(school_id=1, rev=1080, day_key="2026-04-20")
        self.redis.set(sm._materialized_rev_key(1, "2026-04-20"), "1081")

        job = sm.dequeue_snapshot_build(block_timeout=0)

        self.assertIsNotNone(job)
        self.assertTrue(job["_skip_complete"])
        self.assertEqual(job["_skip_reason"], "already_materialized_latest")

    def test_different_schools_and_days_do_not_collide(self):
        sm.enqueue_snapshot_build(school_id=1, rev=10, day_key="2026-04-20")
        sm.enqueue_snapshot_build(school_id=2, rev=10, day_key="2026-04-20")
        sm.enqueue_snapshot_build(school_id=1, rev=10, day_key="2026-04-21")

        self.assertEqual(self.redis.llen(sm._queue_name()), 3)
        self.assertEqual(self.redis.get(sm._latest_rev_key(1, "2026-04-20")), "10")
        self.assertEqual(self.redis.get(sm._latest_rev_key(2, "2026-04-20")), "10")
        self.assertEqual(self.redis.get(sm._latest_rev_key(1, "2026-04-21")), "10")

    def test_worker_unavailable_fallback_still_skips_enqueue(self):
        with override_settings(DISPLAY_SNAPSHOT_REQUIRE_WORKER_ALIVE=True):
            with patch.object(sm, "snapshot_worker_status", return_value={"alive": False}):
                result = sm.enqueue_snapshot_build(school_id=1, rev=10, day_key="2026-04-20")

        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "worker_unavailable")
        self.assertEqual(self.redis.llen(sm._queue_name()), 0)

    def test_pending_job_completion_does_not_delete_newer_pending_job(self):
        first = sm.enqueue_snapshot_build(school_id=1, rev=10, day_key="2026-04-20")["job"]
        pending_key = sm._pending_job_key(1, "2026-04-20")
        self.redis.set(pending_key, "newer-job")

        sm.complete_snapshot_job(first)

        self.assertEqual(self.redis.get(pending_key), "newer-job")

    def test_enqueue_skips_when_latest_revision_is_already_cached(self):
        snap = {
            "meta": {"schedule_revision": 1081, "is_active_window": True},
            "settings": {"refresh_interval_sec": 30},
            "state": {"type": "period"},
            "day_path": [],
            "period_classes": [],
            "period_classes_map": {},
            "standby": [],
            "excellence": [],
            "announcements": [],
        }
        steady_key = av._steady_cache_key_for_school_rev(1, 1081, day_key="2026-04-20")
        fake_cache = SimpleNamespace(
            get=lambda key: av._snapshot_cache_entry(snap) if key == steady_key else None
        )

        with patch.object(sm, "cache", fake_cache):
            result = sm.enqueue_snapshot_build(school_id=1, rev=1081, day_key="2026-04-20")

        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "already_cached")
        self.assertEqual(self.redis.llen(sm._queue_name()), 0)

    def test_enqueue_payload_uses_latest_revision_when_revision_advances(self):
        with patch.object(sm, "_redis_set_latest_revision", return_value=(1082, True)):
            result = sm.enqueue_snapshot_build(school_id=1, rev=1080, day_key="2026-04-20")

        self.assertTrue(result["queued"])
        self.assertEqual(result["job"]["rev"], 1082)


class SnapshotCacheValidationTests(SimpleTestCase):
    def test_validated_cache_entry_rejects_older_revision(self):
        snap = {
            "meta": {"schedule_revision": 5, "is_active_window": True},
            "settings": {"refresh_interval_sec": 30},
            "state": {"type": "period"},
            "day_path": [],
            "period_classes": [],
            "period_classes_map": {},
            "standby": [],
            "excellence": [],
            "announcements": [],
        }

        entry, reason = av._validated_snapshot_cache_entry_from_value(
            av._snapshot_cache_entry(snap),
            min_rev=6,
        )

        self.assertIsNone(entry)
        self.assertEqual(reason, "older_revision")

    def test_validated_cache_entry_rejects_before_hours_after_wake_boundary(self):
        snap = {
            "meta": {
                "schedule_revision": 6,
                "is_active_window": False,
                "next_wake_at": (timezone.now() - timedelta(minutes=1)).isoformat(),
            },
            "settings": {"refresh_interval_sec": 60},
            "state": {"type": "off", "reason": "before_hours"},
            "day_path": [],
            "period_classes": [],
            "period_classes_map": {},
            "standby": [],
            "excellence": [],
            "announcements": [],
        }

        entry, reason = av._validated_snapshot_cache_entry_from_value(
            av._snapshot_cache_entry(snap),
            min_rev=6,
        )

        self.assertIsNone(entry)
        self.assertEqual(reason, "past_wake_boundary")


class SnapshotObservabilityTests(SimpleTestCase):
    def test_snapshot_cache_hit_metrics_survive_log_sampling(self):
        metric_keys: list[str] = []

        with patch.object(so, "metric_incr", side_effect=lambda key, delta=1, ttl=so.METRIC_TTL_SEC: metric_keys.append(key)):
            with patch.object(so, "_should_sample_log", return_value=False):
                with patch.object(so, "log_event") as log_event:
                    so.observe_snapshot_cache(
                        logger=SimpleNamespace(info=lambda *args, **kwargs: None),
                        outcome="hit",
                        layer="steady",
                        school_id=7,
                        rev=42,
                        day_key="2026-04-23",
                    )

        self.assertIn("metrics:snapshot_cache:hit", metric_keys)
        log_event.assert_not_called()

    def test_snapshot_metrics_payload_groups_new_counters(self):
        values = {
            "metrics:snapshot_cache:hit": 4,
            "metrics:snapshot_cache:miss": 2,
            "metrics:snapshot_cache:revision_reject": 1,
            "metrics:snapshot_cache:wake_boundary_reject": 3,
            "metrics:snapshot_build:count": 5,
            "metrics:snapshot_build:soft_timeout": 1,
            "metrics:snapshot_build:duration_ms:sum": 500,
            "metrics:snapshot_build:duration_ms:max": 200,
            "metrics:snapshot_build:source:inline:count": 2,
            "metrics:snapshot_build:source:queue:count": 2,
            "metrics:snapshot_build:source:stale:count": 1,
            "metrics:snapshot_queue:enqueue_count": 6,
            "metrics:snapshot_queue:skipped_enqueue": 4,
            "metrics:snapshot_queue:deduplicated_jobs": 3,
            "metrics:snapshot_queue:queue_wait_time_ms:sum": 1200,
            "metrics:snapshot_queue:queue_wait_time_ms:max": 700,
            "metrics:snapshot_queue:queue_wait_time_ms:count": 4,
        }

        with patch.object(so, "metric_get_int", side_effect=lambda key: int(values.get(key, 0))):
            payload = so.snapshot_metrics_payload()

        self.assertEqual(payload["snapshot_cache"]["hit"], 4)
        self.assertEqual(payload["snapshot_cache"]["miss"], 2)
        self.assertEqual(payload["snapshot_build"]["count"], 5)
        self.assertEqual(payload["snapshot_build"]["soft_timeout"], 1)
        self.assertEqual(payload["snapshot_build"]["duration_ms_avg"], 100)
        self.assertEqual(payload["snapshot_build"]["source"]["inline"]["count"], 2)
        self.assertEqual(payload["queue"]["enqueue_count"], 6)
        self.assertEqual(payload["queue"]["queue_wait_time_ms_avg"], 300)

    @override_settings(DEBUG=True)
    def test_metrics_endpoint_includes_snapshot_observability(self):
        request = RequestFactory().get("/api/display/metrics/")
        fake_payload = {"snapshot_cache": {"hit": 1, "miss": 0}}
        fake_cache = SimpleNamespace(get=lambda key: 0)
        with patch.object(av, "cache", fake_cache):
            with patch.object(av, "_snapshot_metrics_payload", return_value=fake_payload):
                response = av.metrics(request)
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIn("snapshot_observability", data)
        self.assertIn("snapshot_cache", data["snapshot_observability"])
