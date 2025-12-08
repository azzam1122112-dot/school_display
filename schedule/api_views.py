from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone
from hijri_converter import convert

from core.utils import validate_display_token
from .models import SchoolSettings
from .api_serializers import SchoolSettingsSerializer
from .services import compute_today_state, get_current_lessons


# -----------------------------------------------------------
#  🔵 1) API: بيانات شاشة العرض الأساسية (اليوم، التاريخ، الإعدادات)
# -----------------------------------------------------------
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def today_display(request):
    """
    تُعيد إعدادات المدرسة + التاريخ الهجري والميلادي + حالة اليوم والحصة الحالية.
    """
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Forbidden"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
    if not settings_obj:
        return Response({"detail": "School settings not configured."}, status=503)

    today = timezone.localdate()

    # ---------------- التاريخ الميلادي ----------------
    gregorian = {
        "year": today.year,
        "month": today.month,
        "day": today.day,
    }

    # ---------------- التاريخ الهجري ----------------
    hijri_date = convert.Gregorian(today.year, today.month, today.day).to_hijri()
    hijri = {
        "year": hijri_date.year,
        "month": hijri_date.month,
        "day": hijri_date.day,
    }

    # ---------------- الحزمة الأساسية ----------------
    payload = {
        "settings": SchoolSettingsSerializer(settings_obj).data,
        "date_info": {
            "weekday": timezone.localtime().strftime("%A"),
            "gregorian": gregorian,
            "hijri": hijri,
        },
    }

    # ---------------- اليوم + الحصة + الفترة الحالية ----------------
    state = compute_today_state(settings_obj)
    payload.update(state)

    return Response(payload, status=200)


# -----------------------------------------------------------
#  🔵 2) API: إرجاع الإعدادات فقط
# -----------------------------------------------------------
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_settings(request):
    """
    تُعيد إعدادات المدرسة فقط (للاستخدام من display.html)
    """
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Forbidden"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
    if not settings_obj:
        return Response({}, status=200)

    data = SchoolSettingsSerializer(settings_obj).data
    return Response(data, status=200)


# -----------------------------------------------------------
#  🔥 3) API: جدول الحصة الحالية لجميع الفصول (Scrolling List)
# -----------------------------------------------------------
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def current_period_classes(request):
    """
    تُعيد الحصة الجارية والفصول المرتبطة بها، لاستخدامها في شاشة العرض
    لعرض جدول الحصة الحالية بتمرير تلقائي مثل حصص الانتظار.

    تعتمد على get_current_lessons في services.py حتى تبقى منسجمة
    مع منطق الجدول الأحدث وحصص الانتظار.
    """
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Forbidden"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
    if not settings_obj:
        return Response(
            {
                "period": None,
                "period_index": None,
                "period_name": None,
                "scroll_speed": None,
                "classes": [],
            },
            status=200,
        )

    # يستخدم منطق موحّد مع الجدول وحصص الانتظار
    lessons_state = get_current_lessons(settings_obj)
    period = lessons_state.get("period")
    lessons = lessons_state.get("lessons", [])

    # سرعة التمرير الجديدة لجدول الحصص من إعدادات المدرسة
    # (مع افتراضي بسيط لو الحقل لسه ما أُضيف)
    scroll_speed = getattr(settings_obj, "periods_scroll_speed", None)

    if not period:
        return Response(
            {
                "period": None,
                "period_index": None,
                "period_name": None,
                "scroll_speed": scroll_speed,
                "classes": [],
            },
            status=200,
        )

    # تجهيز البيانات بشكل بسيط للقالب (قائمة طويلة مع سطر لكل فصل)
    classes_payload = []
    for item in lessons:
        classes_payload.append(
            {
                "class": item.get("class_name", ""),
                "subject": item.get("subject", ""),
                "teacher": item.get("teacher", ""),
                # لو حبيت تميز لاحقاً بين حصة عادية / انتظار
                "type": item.get("type", "normal"),
            }
        )

    return Response(
        {
            "period": period,                         # {index, start, end}
            "period_index": period.get("index"),
            "period_name": f"الحصة {period.get('index')}",
            "scroll_speed": scroll_speed,             # periods_scroll_speed من الإعدادات
            "classes": classes_payload,               # الفصول الحالية
        },
        status=200,
    )
