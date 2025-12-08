from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from website import views as website_views

urlpatterns = [
    path("cpanel-123/", admin.site.urls),
    path("", website_views.home, name="home"),     # الصفحة الرئيسية/العرض
    path("dashboard/", include("dashboard.urls")),  # لوحة التحكم
    path("api/", include("core.api_urls")),  # سنُعرّف api لاحقًا
    path("schedule/", include("schedule.urls")),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)