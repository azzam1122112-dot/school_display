# website/urls.py
from django.urls import path
from . import views

app_name = "website"

urlpatterns = [
    path("", views.health, name="home"),          # مؤقت للفحص
    path("display/", views.display, name="display"),
]
