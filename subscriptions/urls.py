# subscriptions/urls.py
from django.urls import path
from dashboard import views as dashboard_views

app_name = "subscriptions"

urlpatterns = [
    path("", dashboard_views.system_subscriptions_list, name="system_subscriptions_list"),
    path("add/", dashboard_views.system_subscription_create, name="system_subscription_create"),
    path("<int:pk>/edit/", dashboard_views.system_subscription_edit, name="system_subscription_edit"),
    path("<int:pk>/delete/", dashboard_views.system_subscription_delete, name="system_subscription_delete"),
]
