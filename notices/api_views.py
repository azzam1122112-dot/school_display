# notices/api_views.py
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Announcement, Excellence
from .api_serializers import AnnouncementSerializer, ExcellenceSerializer

@api_view(["GET"])
@permission_classes([AllowAny])
def active_announcements(request):
    now = timezone.now()
    qs = Announcement.objects.filter(is_active=True).order_by("-starts_at")
    # تنقية الصلاحية
    items = [a for a in qs if a.active_now]
    return Response({"items": AnnouncementSerializer(items, many=True).data})

@api_view(["GET"])
@permission_classes([AllowAny])
def active_excellence(request):
    now = timezone.now()
    qs = Excellence.objects.order_by("priority", "-start_at")
    items = [e for e in qs if e.active_now]
    return Response({"items": ExcellenceSerializer(items, many=True).data})
