# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

from website import views as website_views
from website.views import short_display_redirect


urlpatterns = [
    path("cpanel-123/", admin.site.urls),

    path("", website_views.home, name="home"),

    # صفحة الاشتراكات العامة (Landing)
    path("subscriptions-page/", website_views.subscriptions, name="subscriptions"),

    # موقع الويب
    path("", include(("website.urls", "website"), namespace="website")),

    # لوحة التحكم
    path("dashboard/", include(("dashboard.urls", "dashboard"), namespace="dashboard")),

    # API Root
    path("api/", include(("core.api_urls", "core_api"), namespace="core_api")),

    # Schedule (لو عندك صفحات غير API)
    path("schedule/", include(("schedule.urls", "schedule"), namespace="schedule")),

    # رابط مختصر للشاشات
    path("s/<str:short_code>", short_display_redirect, name="short_display_redirect"),

    # favicon
    path("favicon.ico", RedirectView.as_view(url="/static/favicon.ico", permanent=True)),
]


# ✅ تضمين الاشتراكات إذا كان أي تطبيق يبدأ بـ 'subscriptions' في INSTALLED_APPS
if any(app.startswith("subscriptions") for app in settings.INSTALLED_APPS):
    urlpatterns += [
        path("subscriptions/", include(("subscriptions.urls", "subscriptions"), namespace="subscriptions")),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
