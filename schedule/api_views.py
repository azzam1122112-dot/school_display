# schedule/api_views.py
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils import timezone

from hijri_converter import convert
from core.utils import validate_display_token

from .models import SchoolSettings
from .api_serializers import SchoolSettingsSerializer
from .services import compute_today_state

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def today_display(request):
    """
    يُرجع:
      settings     — معلومات المدرسة
      date_info    — {hijri, gregorian, weekday}
      state        — حالة اليوم (before/period/break/after + العدّاد)
      day          — periods/breaks
    """
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Invalid token"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
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
    return Response(payload, status=200)

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_settings(request):
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Invalid token"}, status=403)

    settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
    if not settings_obj:
        return Response({})
    return Response(SchoolSettingsSerializer(settings_obj).data, status=200)
