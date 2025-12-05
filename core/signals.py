import logging
from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.forms.models import model_to_dict
from core.core.firebase import get_db
from notices.models import Announcement, Excellence
from schedule.models import SchoolSettings, DaySchedule, Period, Break

logger = logging.getLogger(__name__)

def sync_to_firestore(collection, doc_id, data):
    """Helper to sync data to Firestore"""
    if not getattr(settings, 'USE_FIREBASE', False):
        return

    try:
        db = get_db()
        doc_ref = db.collection(collection).document(str(doc_id))
        doc_ref.set(data)
        logger.info(f"Synced {collection}/{doc_id} to Firestore.")
    except Exception as e:
        logger.error(f"Error syncing to Firestore: {e}")

def delete_from_firestore(collection, doc_id):
    """Helper to delete data from Firestore"""
    if not getattr(settings, 'USE_FIREBASE', False):
        return

    try:
        db = get_db()
        db.collection(collection).document(str(doc_id)).delete()
        logger.info(f"Deleted {collection}/{doc_id} from Firestore.")
    except Exception as e:
        logger.error(f"Error deleting from Firestore: {e}")

# ---------------------------------------------------------
# 1. Announcements Sync
# ---------------------------------------------------------
@receiver(post_save, sender=Announcement)
def sync_announcement(sender, instance, **kwargs):
    data = {
        "title": instance.title,
        "body": instance.body,
        "level": instance.level,
        "starts_at": instance.starts_at,
        "expires_at": instance.expires_at,
        "is_active": instance.is_active,
        "active_now": instance.active_now,  # Computed property
    }
    sync_to_firestore("announcements", instance.pk, data)

@receiver(post_delete, sender=Announcement)
def delete_announcement(sender, instance, **kwargs):
    delete_from_firestore("announcements", instance.pk)

# ---------------------------------------------------------
# 2. Excellence Sync
# ---------------------------------------------------------
@receiver(post_save, sender=Excellence)
def sync_excellence(sender, instance, **kwargs):
    data = {
        "teacher_name": instance.teacher_name,
        "reason": instance.reason,
        "photo_url": instance.image_src, # Use the computed property for the final URL
        "start_at": instance.start_at,
        "end_at": instance.end_at,
        "priority": instance.priority,
        "active_now": instance.active_now,
    }
    sync_to_firestore("excellence", instance.pk, data)

@receiver(post_delete, sender=Excellence)
def delete_excellence(sender, instance, **kwargs):
    delete_from_firestore("excellence", instance.pk)

# ---------------------------------------------------------
# 3. School Settings Sync
# ---------------------------------------------------------
@receiver(post_save, sender=SchoolSettings)
def sync_settings(sender, instance, **kwargs):
    data = {
        "name": instance.name,
        "logo_url": instance.logo_url,
        "theme": instance.theme,
        "timezone_name": instance.timezone_name,
        "refresh_interval_sec": instance.refresh_interval_sec,
        "standby_scroll_speed": instance.standby_scroll_speed,
    }
    # We use a fixed ID 'main' or the PK if multiple settings are allowed (usually one)
    sync_to_firestore("settings", "school_config", data)

# ---------------------------------------------------------
# 4. Schedule Sync (Complex)
# ---------------------------------------------------------
def sync_day_schedule(day_instance):
    """
    Syncs a full day schedule including its periods and breaks.
    Structure in Firestore: schedule/{weekday_number}
    """
    if not day_instance:
        return

    # Prepare Periods
    periods = []
    for p in day_instance.periods.all().order_by('index'):
        periods.append({
            "index": p.index,
            "starts_at": p.starts_at.strftime("%H:%M:%S"),
            "ends_at": p.ends_at.strftime("%H:%M:%S"),
        })

    # Prepare Breaks
    breaks = []
    for b in day_instance.breaks.all().order_by('starts_at'):
        breaks.append({
            "label": b.label,
            "starts_at": b.starts_at.strftime("%H:%M:%S"),
            "duration_min": b.duration_min,
            "ends_at": b.ends_at.strftime("%H:%M:%S"),
        })

    data = {
        "weekday": day_instance.weekday,
        "weekday_display": day_instance.get_weekday_display(),
        "is_active": day_instance.is_active,
        "periods_count": day_instance.periods_count,
        "periods": periods,
        "breaks": breaks,
    }
    
    sync_to_firestore("schedule", str(day_instance.weekday), data)

@receiver(post_save, sender=DaySchedule)
def on_day_save(sender, instance, **kwargs):
    sync_day_schedule(instance)

# Trigger sync when child models (Period/Break) change
@receiver(post_save, sender=Period)
@receiver(post_delete, sender=Period)
def on_period_change(sender, instance, **kwargs):
    sync_day_schedule(instance.day)

@receiver(post_save, sender=Break)
@receiver(post_delete, sender=Break)
def on_break_change(sender, instance, **kwargs):
    sync_day_schedule(instance.day)
