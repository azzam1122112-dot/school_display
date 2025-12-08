from django.urls import path, include
from . import api_views

urlpatterns = [
    path("ping/", api_views.ping, name="ping"),
    path("display/", include("schedule.api_urls")),
    path("standby/", include("standby.api_urls")),
    path("announcements/", include("notices.api_urls")),
]
