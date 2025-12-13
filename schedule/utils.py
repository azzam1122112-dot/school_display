# schedule/utils.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging

from django.utils import timezone

from core.models import School
from .models import SchoolSettings

logger = logging.getLogger(__name__)

# نحاول استيراد الخدمات الحقيقية من schedule.services
try:
    from .services import compute_today_state, get_current_lessons  # type: ignore
except Exception:  # pragma: no cover - في حال غياب الملف أو حدوث خطأ
    compute_today_state = None  # type: ignore[assignment]
    get_current_lessons = None  # type: ignore[assignment]


def _get_school_settings_for_display(school: School) -> SchoolSettings:
    """
    جلب إعدادات الجدول الخاصة بالمدرسة.

    - إذا وُجد كائن SchoolSettings للمدرسة → نستخدمه.
    - إذا لم يوجد → ننشئ كائن غير محفوظ في قاعدة البيانات بقيم افتراضية
      حتى تعمل الخدمات أو الـ fallback بدون كسر.
    """
    try:
        return SchoolSettings.objects.get(school=school)
    except SchoolSettings.DoesNotExist:
        # كائن مؤقت غير محفوظ، يكفي لتمريره إلى الخدمات أو إرجاع حالة افتراضية
        return SchoolSettings(school=school)


def get_today_state(school: School) -> Dict[str, Any]:
    """
    الدالة القياسية التي تستخدمها شاشة العرض للحصول على:
      - معلومات التاريخ.
      - حالة اليوم (داخل حصة / بين الحصص / خارج الدوام / إجازة).
      - قائمة الحصص (periods) والفترات البينية (breaks).

    * تعيد نفس البنية التي يتوقعها dashboard/api_display.py:
      today_state["state"] يجب أن يكون قاموسًا يحتوي على "type".
    """
    settings = _get_school_settings_for_display(school)

    # إذا توفّرت الدالة الحقيقية في services نحاول استخدامها أولاً
    if compute_today_state is not None:
        try:
            # ⚠️ بدون keyword "today" حتى لا يحدث TypeError
            state = compute_today_state(settings)  # type: ignore[misc]

            # نتأكد أننا نرجع dict كما يتوقع الكود الأعلى
            if isinstance(state, dict):
                # ضمان الحد الأدنى من البنية المطلوبة
                inner_state = state.get("state")
                if not isinstance(inner_state, dict):
                    # نحاول تطبيعها إلى dict حتى لا تنكسر _compute_refresh_hint
                    state["state"] = {
                        "type": str(inner_state or "unknown"),
                    }
                return state

            # في حال رجعت الخدمات كائن مخصص فيه to_dict
            if hasattr(state, "to_dict"):
                state_dict = state.to_dict()  # type: ignore[call-arg]
                if isinstance(state_dict, dict):
                    inner_state = state_dict.get("state")
                    if not isinstance(inner_state, dict):
                        state_dict["state"] = {
                            "type": str(inner_state or "unknown"),
                        }
                    return state_dict

            # نوع غير مدعوم → ننتقل للـ fallback
            logger.warning(
                "compute_today_state رجعت نوعًا غير مدعوم (%s)، سيتم استخدام حالة افتراضية.",
                type(state),
            )
        except Exception:
            logger.exception("فشل compute_today_state، سيتم إرجاع حالة افتراضية لشاشة العرض.")

    # ✅ Fallback آمن ومتوافق مع dashboard/api_display._compute_refresh_hint
    today = timezone.localdate()
    now = timezone.localtime()

    return {
        "date_info": {
            "today": today,
            "weekday": now.weekday(),
            "weekday_display": now.strftime("%A"),
        },
        # مهم: يكون dict وليس نص
        "state": {
            "type": "off",          # off / before / period / break / after / holiday ...
            "label": "خارج وقت الدوام",
        },
        "periods": [],             # لا يوجد جدول متاح حاليًا
        "breaks": [],
        # هذا الحقل لا يُستخدم كثيرًا من شاشة العرض؛ api_display يحقن DisplaySettings خارجيًا
        "settings": None,
    }


def get_period_classes_now(school: School) -> List[Dict[str, Any]]:
    """
    إرجاع قائمة الحصص/الفصول الجارية الآن بصيغة مبسّطة للاستهلاك من واجهة العرض.

    الشكل المتوقع لكل عنصر:
    {
        "class_name": "...",
        "subject": "...",
        "teacher": "...",
        "type": "normal" | "standby" | ...
    }

    تعتمد على الدالة get_current_lessons في schedule.services إن توفرت،
    وإلا تعيد قائمة فارغة بدون كسر الواجهة.
    """
    settings = _get_school_settings_for_display(school)

    if get_current_lessons is None:
        return []

    try:
        result = get_current_lessons(settings)  # type: ignore[misc]
        # نتوقع شيئًا مثل:
        # {
        #     "period": { ... معلومات الحصة الحالية ... } أو None
        #     "lessons": [
        #         {"class_name": ..., "subject": ..., "teacher": ..., "type": ...},
        #         ...
        #     ],
        # }
        lessons = result.get("lessons", []) if isinstance(result, dict) else []

        normalized: List[Dict[str, Any]] = []
        for item in lessons:
            if not isinstance(item, dict):
                # حماية إضافية في حال تغيّر شكل البيانات لاحقًا
                continue

            normalized.append(
                {
                    "class_name": item.get("class_name", ""),
                    "subject": item.get("subject", ""),
                    "teacher": item.get("teacher", ""),
                    "type": item.get("type", "normal"),
                }
            )

        return normalized
    except Exception:
        logger.exception("فشل get_current_lessons، سيتم إرجاع قائمة حصص فارغة.")
        return []


__all__ = [
    "get_today_state",
    "get_period_classes_now",
]
