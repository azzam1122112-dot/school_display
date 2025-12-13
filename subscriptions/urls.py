from django.urls import path
from dashboard import views

app_name = "subscriptions"

urlpatterns = [
    path("add/", views.system_subscription_create, name="create"),
    path("<int:pk>/edit/", views.system_subscription_edit, name="edit"),
    path("<int:pk>/delete/", views.system_subscription_delete, name="delete"),
]
