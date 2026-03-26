from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


def favicon(request):
    """Serve favicon without redirect and without streaming (ASGI-friendly)."""
    content = None

    # 1) Prefer finders (works in dev without collectstatic)
    try:
        found_path = finders.find("favicon.ico")
        if found_path:
            with open(found_path, "rb") as f:
                content = f.read()
    except Exception:
        content = None

    # 2) Fallback to storage (works in production after collectstatic)
    if content is None:
        try:
            with staticfiles_storage.open("favicon.ico", "rb") as f:
                content = f.read()
        except Exception:
            return HttpResponse(status=404)

    resp = HttpResponse(content, content_type="image/x-icon")
    # Cache aggressively; file changes are fingerprinted by collectstatic/staticfiles.
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


def robots_txt(request):
    """Serve robots.txt safely in dev/test/prod without import-time static URL resolution."""
    content = None

    # 1) Prefer finders (works in dev/test without collectstatic)
    try:
        found_path = finders.find("robots.txt")
        if found_path:
            with open(found_path, "rb") as f:
                content = f.read()
    except Exception:
        content = None

    # 2) Fallback to storage (works in production after collectstatic)
    if content is None:
        try:
            with staticfiles_storage.open("robots.txt", "rb") as f:
                content = f.read()
        except Exception:
            content = b"User-agent: *\nAllow: /\n"

    resp = HttpResponse(content, content_type="text/plain; charset=utf-8")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


urlpatterns = [
    path("cpanel-123/", admin.site.urls),

    # favicon (serve directly; avoids /static/* and avoids streaming under ASGI)
    path("favicon.ico", favicon, name="favicon"),

    # robots.txt (serve directly to avoid startup/runtime failures in test/dev)
    path("robots.txt", robots_txt, name="robots_txt"),

    # موقع الويب (يشمل / و /subscriptions-page/ و /s/<code>)
    path("", include(("website.urls", "website"), namespace="website")),

    # لوحة التحكم
    path("dashboard/", include(("dashboard.urls", "dashboard"), namespace="dashboard")),

    # API Root
    path("api/", include(("core.api_urls", "core_api"), namespace="core_api")),

    # Schedule (لو عندك صفحات غير API)
    path("schedule/", include(("schedule.urls", "schedule"), namespace="schedule")),

]


# ✅ تضمين الاشتراكات إذا كان أي تطبيق يبدأ بـ 'subscriptions' في INSTALLED_APPS
if any(app.startswith("subscriptions") for app in settings.INSTALLED_APPS):
    urlpatterns += [
        path("subscriptions/", include(("subscriptions.urls", "subscriptions"), namespace="subscriptions")),
    ]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
