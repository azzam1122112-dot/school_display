from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("website.urls")),       # الصفحة الرئيسية/العرض
    path("dashboard/", include("dashboard.urls")),  # لوحة التحكم
    path("api/", include("core.api_urls")),  # سنُعرّف api لاحقًا
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)