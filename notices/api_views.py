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
    if not hasattr(request, 'school') or not request.school:
        return Response({"detail": "Unauthorized"}, status=403)

    now = timezone.now()
    qs = Announcement.objects.filter(school=request.school, is_active=True).order_by("-starts_at")
    # تنقية الصلاحية
    items = [a for a in qs if a.active_now]
    return Response({"items": AnnouncementSerializer(items, many=True).data})

@api_view(["GET"])
@permission_classes([AllowAny])
def active_excellence(request):
    """
    يعيد بطاقات التميّز النشطة.
    يتأكد من تمرير request في السياق حتى تعمل روابط الصور.
    """
    if not hasattr(request, 'school') or not request.school:
        return Response({"detail": "Unauthorized"}, status=403)

    now = timezone.now()
    qs = Excellence.objects.filter(school=request.school).order_by("priority", "-start_at")
    items = [e for e in qs if e.active_now]
    serializer = ExcellenceSerializer(items, many=True, context={"request": request})
    return Response({"items": serializer.data})
