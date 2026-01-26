# schedule/api_urls.py
from django.urls import path
from . import api_views

app_name = "display_api"

urlpatterns = [
    # Status / polling endpoint
    path("status/", api_views.status, name="status"),
    path("status/<str:token>/", api_views.status, name="status_token"),

    # Canonical endpoint
    path("snapshot/", api_views.snapshot, name="snapshot"),
    path("snapshot/<str:token>/", api_views.snapshot, name="snapshot_token"),

    # Backward compatible aliases
    path("today/", api_views.snapshot, name="today"),
    path("today/<str:token>/", api_views.snapshot, name="today_token"),

    path("live/", api_views.snapshot, name="live"),
    path("live/<str:token>/", api_views.snapshot, name="live_token"),

    # Health (keep original if simple)
    path("ping/", api_views.ping, name="ping"),
]
