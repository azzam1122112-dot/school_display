# schedule/api_views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone

from hijri_converter import convert

from .models import SchoolSettings
from .api_serializers import SchoolSettingsSerializer, DayScheduleSerializer
from .services import compute_today_state

@api_view(["GET"])
@permission_classes([AllowAny])  # القراءة عامة لواجهة الشاشة
def today_display(request):
    """
    يُرجع:
      settings     — معلومات المدرسة
      date_info    — {hijri, gregorian, weekday}
      state        — حالة اليوم (before/period/break/after + العدّاد)
      day          — periods/breaks
    """
    # التحقق من وجود مدرسة مرتبطة بالطلب (عبر التوكن)
    if not hasattr(request, 'school') or not request.school:
        return Response(
            {"detail": "لم يتم تحديد المدرسة (Token مفقود أو غير صالح)."},
            status=403,
        )

    settings_obj = SchoolSettings.objects.filter(school=request.school).first()
    if not settings_obj:
        return Response(
            {"detail": "لم يتم ضبط إعدادات المدرسة بعد."},
            status=503,
        )

    today = timezone.localdate()
    g = {"year": today.year, "month": today.month, "day": today.day}
    h = convert.Gregorian(today.year, today.month, today.day).to_hijri()

    payload = {
        "settings": SchoolSettingsSerializer(settings_obj).data,
        "date_info": {
            "weekday": timezone.localtime().strftime("%A"),  # اسم اليوم المحلي
            "gregorian": g,
            "hijri": {"year": h.year, "month": h.month, "day": h.day},
        },
    }
    payload.update(compute_today_state(settings_obj))
    return Response(payload)

@api_view(["GET"])
@permission_classes([AllowAny])
def get_settings(request):
    if not hasattr(request, 'school') or not request.school:
        return Response({"detail": "Unauthorized"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=request.school).first()
    if not settings_obj:
        return Response({})
    return Response(SchoolSettingsSerializer(settings_obj).data)
