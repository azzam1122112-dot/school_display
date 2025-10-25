# core/api_urls.py
from django.urls import path, include
from . import api_views

urlpatterns = [
    path("ping/", api_views.ping, name="ping"),
    path("display/", include("schedule.api_urls")),       # /api/display/today/
    path("standby/", include("standby.api_urls")),        # /api/standby/today/
    path("announcements/", include("notices.api_urls")),  # /api/announcements/active/ + /api/announcements/excellence/
]
