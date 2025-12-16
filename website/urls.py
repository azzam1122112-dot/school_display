from django.urls import path
from . import views

app_name = "website"

urlpatterns = [
    # الصفحة الرئيسية الفعلية (تعرض الشاشة حسب token/short_code في querystring)
    path("", views.home, name="home"),

    # صفحة الاشتراكات العامة (Landing)
    path("subscriptions-page/", views.subscriptions, name="subscriptions"),

    # Health check
    path("health/", views.health, name="health"),

    # ✅ رابط مختصر (يدعم مع وبدون slash لتفادي 404)
    path("s/<str:short_code>/", views.short_display_redirect, name="short_display"),
    path("s/<str:short_code>", views.short_display_redirect),

    # (اختياري) إذا عندك استخدام داخلي
    # path("display/", views.display, name="display"),
]
