from django.test import TestCase
from django.utils import timezone

from core.models import School, SubscriptionPlan
from subscriptions.models import SchoolSubscription
from subscriptions.utils import school_has_active_subscription


class SubscriptionSyncTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="Test School", slug="test-school", is_active=False)
        self.plan = SubscriptionPlan.objects.create(code="basic", name="Basic", price_monthly=0)

    def test_school_sync_active_on_save(self):
        SchoolSubscription.objects.create(
            school=self.school,
            plan=self.plan,
            status="active",
            starts_at=timezone.localdate(),
            ends_at=None,
        )

        self.school.refresh_from_db()
        self.assertTrue(self.school.is_active)
        self.assertTrue(school_has_active_subscription(self.school.id))

    def test_school_sync_inactive_on_expired(self):
        yesterday = timezone.localdate() - timezone.timedelta(days=1)
        SchoolSubscription.objects.create(
            school=self.school,
            plan=self.plan,
            status="active",
            starts_at=yesterday,
            ends_at=yesterday,  # منتهي
        )

        self.school.refresh_from_db()
        self.assertFalse(self.school.is_active)
        self.assertFalse(school_has_active_subscription(self.school.id))

    def test_school_sync_inactive_on_delete(self):
        sub = SchoolSubscription.objects.create(
            school=self.school,
            plan=self.plan,
            status="active",
            starts_at=timezone.localdate(),
            ends_at=None,
        )

        self.school.refresh_from_db()
        self.assertTrue(self.school.is_active)

        sub.delete()
        self.school.refresh_from_db()
        self.assertFalse(self.school.is_active)
