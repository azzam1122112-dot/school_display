# core/api_urls.py
from django.urls import path, include
from . import api_views
from dashboard.api_display import display_snapshot

app_name = "core_api"

urlpatterns = [
    path("ping/", api_views.ping, name="ping"),

    # Display API (مرة واحدة فقط)
    path("display/", include(("schedule.api_urls", "display_api"), namespace="display_api")),
    path("display/snapshot/<str:token>/", display_snapshot, name="display_snapshot"),

    # باقي الـ APIs
    path("standby/", include(("standby.api_urls", "standby_api"), namespace="standby_api")),
    path("announcements/", include(("notices.api_urls", "notices_api"), namespace="notices_api")),
]
