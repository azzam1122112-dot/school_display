# notices/api_urls.py
from django.urls import path
from . import api_views

urlpatterns = [
    path("active/", api_views.active_announcements, name="active"),
    path("excellence/", api_views.active_excellence, name="excellence"),
]
