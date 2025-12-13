# core/api_urls.py
from django.urls import path, include
from . import api_views

app_name = "core_api"

urlpatterns = [
    path("ping/", api_views.ping, name="ping"),

    # Display API (مرة واحدة فقط)
    path("display/", include(("schedule.api_urls", "display_api"), namespace="display_api")),

    # باقي الـ APIs
    path("standby/", include(("standby.api_urls", "standby_api"), namespace="standby_api")),
    path("announcements/", include(("notices.api_urls", "notices_api"), namespace="notices_api")),
]
