# standby/api_views.py
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import StandbyAssignment
from .api_serializers import StandbySerializer

@api_view(["GET"])
@permission_classes([AllowAny])
def today_standby(request):
    today = timezone.localdate()
    qs = StandbyAssignment.objects.filter(date=today).order_by("period_index", "teacher_name")
    return Response({"date": str(today), "items": StandbySerializer(qs, many=True).data})
