import logging
from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from core.core.firebase import get_db
from notices.models import Announcement, Excellence
from schedule.models import SchoolSettings, DaySchedule, Period, Break

logger = logging.getLogger(__name__)

def sync_to_firestore(school_id, collection, doc_id, data):
    if not getattr(settings, 'USE_FIREBASE', False):
        return
    try:
        db = get_db()
        ref = db.collection('schools').document(str(school_id)).collection(collection).document(str(doc_id))
        ref.set(data)
    except Exception as e:
        logger.error(f"Error syncing to Firestore: {e}")

def delete_from_firestore(school_id, collection, doc_id):
    if not getattr(settings, 'USE_FIREBASE', False):
        return
    try:
        db = get_db()
        db.collection('schools').document(str(school_id)).collection(collection).document(str(doc_id)).delete()
    except Exception as e:
        logger.error(f"Error deleting from Firestore: {e}")

@receiver(post_save, sender=Announcement)
def sync_announcement(sender, instance, **kwargs):
    if not instance.school:
        return
    data = {
        "title": instance.title,
        "body": instance.body,
        "level": instance.level,
        "starts_at": instance.starts_at,
        "expires_at": instance.expires_at,
        "is_active": instance.is_active,
        "active_now": instance.active_now,
    }
    sync_to_firestore(instance.school.id, "announcements", instance.pk, data)

@receiver(post_delete, sender=Announcement)
def delete_announcement(sender, instance, **kwargs):
    if not instance.school:
        return
    delete_from_firestore(instance.school.id, "announcements", instance.pk)

@receiver(post_save, sender=Excellence)
def sync_excellence(sender, instance, **kwargs):
    if not instance.school:
        return
    data = {
        "teacher_name": instance.teacher_name,
        "reason": instance.reason,
        "photo_url": instance.image_src,
        "start_at": instance.start_at,
        "end_at": instance.end_at,
        "priority": instance.priority,
        "active_now": instance.active_now,
    }
    sync_to_firestore(instance.school.id, "excellence", instance.pk, data)

@receiver(post_delete, sender=Excellence)
def delete_excellence(sender, instance, **kwargs):
    if not instance.school:
        return
    delete_from_firestore(instance.school.id, "excellence", instance.pk)

@receiver(post_save, sender=SchoolSettings)
def sync_settings(sender, instance, **kwargs):
    if not instance.school:
        return
    data = {
        "name": instance.name,
        "logo_url": instance.logo_url,
        "theme": instance.theme,
        "timezone_name": instance.timezone_name,
        "refresh_interval_sec": instance.refresh_interval_sec,
        "standby_scroll_speed": instance.standby_scroll_speed,
    }
    sync_to_firestore(instance.school.id, "settings", "config", data)

def sync_day_schedule(day_instance):
    if not day_instance or not day_instance.settings.school:
        return

    periods = [
        {
            "index": p.index,
            "starts_at": p.starts_at.strftime("%H:%M:%S"),
            "ends_at": p.ends_at.strftime("%H:%M:%S"),
        }
        for p in day_instance.periods.all().order_by("index")
    ]

    breaks = [
        {
            "label": b.label,
            "starts_at": b.starts_at.strftime("%H:%M:%S"),
            "duration_min": b.duration_min,
            "ends_at": b.ends_at.strftime("%H:%M:%S"),
        }
        for b in day_instance.breaks.all().order_by("starts_at")
    ]

    data = {
        "weekday": day_instance.weekday,
        "weekday_display": day_instance.get_weekday_display(),
        "is_active": day_instance.is_active,
        "periods_count": day_instance.periods_count,
        "periods": periods,
        "breaks": breaks,
    }

    sync_to_firestore(day_instance.settings.school.id, "schedule", str(day_instance.weekday), data)

@receiver(post_save, sender=DaySchedule)
def on_day_save(sender, instance, **kwargs):
    sync_day_schedule(instance)

@receiver(post_save, sender=Period)
@receiver(post_delete, sender=Period)
def on_period_change(sender, instance, **kwargs):
    sync_day_schedule(instance.day)

@receiver(post_save, sender=Break)
@receiver(post_delete, sender=Break)
def on_break_change(sender, instance, **kwargs):
    sync_day_schedule(instance.day)




# core/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from core.models import UserProfile, School

User = get_user_model()

@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if not created:
        return

    profile, _ = UserProfile.objects.get_or_create(user=instance)

    if profile.schools.exists():
        return

    school = School.objects.first()
    if school:
        profile.schools.add(school)
        profile.active_school = school
        profile.save(update_fields=["active_school"])
