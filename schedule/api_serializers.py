# schedule/api_serializers.py
from rest_framework import serializers
from .models import SchoolSettings, DaySchedule, Period, Break

class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = ("index", "starts_at", "ends_at")

class BreakSerializer(serializers.ModelSerializer):
    ends_at = serializers.TimeField(read_only=True, source="ends_at")
    class Meta:
        model = Break
        fields = ("label", "starts_at", "duration_min", "ends_at")

class DayScheduleSerializer(serializers.ModelSerializer):
    periods = PeriodSerializer(many=True, read_only=True)
    breaks = BreakSerializer(many=True, read_only=True)
    weekday_display = serializers.CharField(source="get_weekday_display", read_only=True)

    class Meta:
        model = DaySchedule
        fields = ("weekday", "weekday_display", "periods_count", "periods", "breaks")

class SchoolSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolSettings
        fields = ("name", "logo_url", "theme", "timezone_name", "refresh_interval_sec", "auto_dark_after_hour")
