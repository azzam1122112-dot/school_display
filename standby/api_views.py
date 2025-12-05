# standby/api_views.py
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from core.utils import validate_display_token

from .models import StandbyAssignment
from .api_serializers import StandbySerializer

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def today_standby(request):
    screen = validate_display_token(request)
    if not screen:
        return Response({"detail": "Invalid token"}, status=403)

    today = timezone.localdate()
    qs = StandbyAssignment.objects.filter(school=screen.school, date=today).order_by("period_index", "teacher_name")
    return Response({"date": str(today), "items": StandbySerializer(qs, many=True).data}, status=200)
