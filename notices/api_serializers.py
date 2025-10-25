# notices/api_serializers.py
from rest_framework import serializers
from .models import Announcement, Excellence

class AnnouncementSerializer(serializers.ModelSerializer):
    active_now = serializers.BooleanField(read_only=True)
    class Meta:
        model = Announcement
        fields = ("title", "body", "level", "starts_at", "expires_at", "is_active", "active_now")

class ExcellenceSerializer(serializers.ModelSerializer):
    active_now = serializers.BooleanField(read_only=True)
    class Meta:
        model = Excellence
        fields = ("teacher_name", "reason", "photo_url", "start_at", "end_at", "priority", "active_now")
