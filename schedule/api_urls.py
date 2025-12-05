# schedule/api_urls.py
from django.urls import path
from . import api_views

urlpatterns = [
    path("today/", api_views.today_display, name="today"),
    path("settings/", api_views.get_settings, name="settings"),
]
