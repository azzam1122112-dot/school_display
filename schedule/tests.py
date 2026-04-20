from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from schedule import snapshot_materializer as sm


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
