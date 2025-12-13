from django.urls import path
from .api import api_current_lessons
from . import views

app_name = "schedule"

urlpatterns = [
    # API محلي (إن كنت ما زلت تستخدمه)
    path(
        "api/current/<int:school_id>/",
        api_current_lessons,
        name="api_current_lessons",
    ),

    # إن لم تكن تستخدم هذا المسار فعليًا يمكن حذفه لاحقًا
    path(
        "api/<int:school_id>/current/",
        views.api_current_lessons,
        name="api_current",
    ),
]
