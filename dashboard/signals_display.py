import logging
from functools import wraps
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from django.core.cache import cache

from .services_display import build_school_snapshot, cache_write_snapshot
from schedule.models import DutyAssignment, Period, SchoolSettings
from notices.models import Announcement
from core.models import School

logger = logging.getLogger(__name__)

# مفتاح مؤقت لمنع التكرار السريع
DEBOUNCE_CACHE_KEY = "debounce:rebuild:school:{}"
DEBOUNCE_SECONDS = 2

def debounce_rebuild(school_id):
    """
    دالة تقوم بجدولة إعادة البناء، مع منع التكرار (Debounce).
    تستخدم transaction.on_commit للتأكد أن البيانات حُفظت في DB.
    """
    if not school_id:
        return

    def _execute_build():
        # تحقق من القفل لتجنب "تسونامي" التحديثات عند حفظ Formset
        lock_key = DEBOUNCE_CACHE_KEY.format(school_id)
        if cache.get(lock_key):
            # تم الجدولة أو التنفيذ مؤخراً، تجاهل
            logger.debug(f"Skipping rebuild for School {school_id} (Debounced)")
            return
        
        # ضع قفل بسيط
        cache.set(lock_key, "1", timeout=DEBOUNCE_SECONDS)
        
        try:
            logger.info(f"Starting snapshot rebuild for School {school_id}")
            data = build_school_snapshot(school_id)
            if data:
                new_ver = cache_write_snapshot(school_id, data)
                logger.info(f"Broadcast new version {new_ver} for School {school_id}")
        except Exception as e:
            logger.error(f"Failed to rebuild snapshot: {e}", exc_info=True)

    # تشغيل الدالة فقط بعد نجاح الكوميت
    transaction.on_commit(_execute_build)


# ------------------------------------------------------------------
# Signal Receivers
# أي تغيير في هذه المودلز يستدعي إعادة بناء الشاشة للمدرسة المعنية
# ------------------------------------------------------------------

@receiver(post_save, sender=SchoolSettings)
def on_settings_change(sender, instance, **kwargs):
    # instance here is SchoolSettings, needs instance.school.id
    if instance.school:
        debounce_rebuild(instance.school.id)

@receiver([post_save, post_delete], sender=Announcement)
def on_notice_change(sender, instance, **kwargs):
    if instance.school:
        debounce_rebuild(instance.school.id)

# DutyAssignment might throw error if imported but not in installed apps fully loaded
# Ensure your apps are loaded or use string reference if needed in full proj
@receiver([post_save, post_delete], sender=DutyAssignment)
def on_schedule_change(sender, instance, **kwargs):
    # DutyAssignment مرتبط بالمدرسة
    if instance.school:
        debounce_rebuild(instance.school.id)
