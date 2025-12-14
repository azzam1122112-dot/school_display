import logging
import os

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        """
        تهيئة تطبيق core.

        - تحميل إشعارات / تكامل Firebase فقط إذا:
          * USE_FIREBASE = True في settings، و
          * متوفر مسار بيانات اعتماد Firebase في متغيرات البيئة.
        - الهدف: منع رسائل الخطأ من نوع "Missing Firebase credentials"
          في بيئة الإنتاج عندما لا نستخدم Firebase.
        """

        # يأتي من settings.py (ENABLE_FIREBASE / USE_FIREBASE)
        use_firebase = getattr(settings, "USE_FIREBASE", False)

        # نحاول قراءة مسار مفاتيح Firebase من متغيّرات البيئة
        creds_path = (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("FIREBASE_CREDENTIALS")
        )

        if not use_firebase:
            # Firebase معطّل بالكامل
            logger.info("Firebase integration is disabled (USE_FIREBASE is False).")
            return

        if not creds_path:
            # مفعّل في الإعدادات لكن لا يوجد مفاتيح → نتجاهل مع تحذير بسيط
            logger.warning(
                "Firebase is enabled but no credentials path is configured. "
                "Skipping Firestore sync signals."
            )
            return

        # في هذه الحالة فقط نستورد signals التي تستخدم Firebase
        try:
            import core.signals  # noqa: F401
            logger.info("Firebase signals loaded successfully.")
        except Exception as exc:  # حماية إضافية
            logger.exception("Failed to load Firebase signals: %s", exc)


def ready(self):
    import core.signals
