# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from website import views as website_views
from django.views.generic import RedirectView

urlpatterns = [
    path("cpanel-123/", admin.site.urls),

    path("", website_views.home, name="home"),
    path("dashboard/", include(("dashboard.urls", "dashboard"), namespace="dashboard")),

    # API Root (كل شيء تحت /api/)
    path("api/", include(("core.api_urls", "core_api"), namespace="core_api")),


    path("favicon.ico", RedirectView.as_view(url="/static/favicon.ico", permanent=True)),

    # صفحات schedule (لو عندك صفحات غير API)
    path("schedule/", include(("schedule.urls", "schedule"), namespace="schedule")),

    path("subscriptions/", include(("subscriptions.urls", "subscriptions"), namespace="subscriptions")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
