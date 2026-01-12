from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView


urlpatterns = [
    path("cpanel-123/", admin.site.urls),

    # موقع الويب (يشمل / و /subscriptions-page/ و /s/<code>)
    path("", include(("website.urls", "website"), namespace="website")),

    # لوحة التحكم
    path("dashboard/", include(("dashboard.urls", "dashboard"), namespace="dashboard")),

    # API Root
    path("api/", include(("core.api_urls", "core_api"), namespace="core_api")),

    # Schedule (لو عندك صفحات غير API)
    path("schedule/", include(("schedule.urls", "schedule"), namespace="schedule")),

    # favicon
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.ico", permanent=True)),

    # robots.txt
    path("robots.txt", RedirectView.as_view(url=staticfiles_storage.url("robots.txt"), permanent=True)),
]


# ✅ تضمين الاشتراكات إذا كان أي تطبيق يبدأ بـ 'subscriptions' في INSTALLED_APPS
if any(app.startswith("subscriptions") for app in settings.INSTALLED_APPS):
    urlpatterns += [
        path("subscriptions/", include(("subscriptions.urls", "subscriptions"), namespace="subscriptions")),
    ]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
