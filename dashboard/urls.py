from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.index, name="index"),

    path("settings/", views.school_settings, name="settings"),

    path("days/", views.days_list, name="days_list"),
    path("days/<int:weekday>/", views.day_edit, name="day_edit"),
    path("days/<int:weekday>/toggle/", views.day_toggle, name="day_toggle"),
    # ⬅️ جديد: تعبئة تلقائية
    path("days/<int:weekday>/autofill/", views.day_autofill, name="day_autofill"),

    path("announcements/", views.ann_list, name="ann_list"),
    path("announcements/new/", views.ann_create, name="ann_create"),
    path("announcements/<int:pk>/edit/", views.ann_edit, name="ann_edit"),
    path("announcements/<int:pk>/delete/", views.ann_delete, name="ann_delete"),

    path("excellence/", views.exc_list, name="exc_list"),
    path("excellence/new/", views.exc_create, name="exc_create"),
    path("excellence/<int:pk>/edit/", views.exc_edit, name="exc_edit"),
    path("excellence/<int:pk>/delete/", views.exc_delete, name="exc_delete"),

    path("standby/", views.standby_list, name="standby_list"),
    path("standby/new/", views.standby_create, name="standby_create"),
    path("standby/<int:pk>/delete/", views.standby_delete, name="standby_delete"),
    path("standby/import/", views.standby_import, name="standby_import"),
    path("days/<int:weekday>/clear/", views.day_clear, name="day_clear"),
    path("days/<int:weekday>/reindex/", views.day_reindex, name="day_reindex"),

]
