# standby/api_serializers.py
from rest_framework import serializers
from .models import StandbyAssignment

class StandbySerializer(serializers.ModelSerializer):
    class Meta:
        model = StandbyAssignment
        fields = ("date", "period_index", "class_name", "teacher_name", "notes")
