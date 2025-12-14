from django.urls import path

from . import views
from dashboard.api_display import display_snapshot

app_name = "dashboard"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("demo-login/", views.demo_login, name="demo_login"),
    path("logout/", views.logout_view, name="logout"),
    path("password/", views.change_password, name="change_password"),
    path("", views.index, name="index"),

    path("settings/", views.school_settings, name="settings"),

    # الحصص (الدروس)
    path("lessons/", views.lessons_list, name="lessons_list"),
    path("lessons/new/", views.lesson_create, name="add_lesson"),
    path("lessons/<int:pk>/edit/", views.lesson_edit, name="edit_lesson"),
    path("lessons/<int:pk>/delete/", views.lesson_delete, name="delete_lesson"),

    # أيام الأسبوع وجدول اليوم
    path("days/", views.days_list, name="days_list"),
    path("days/<int:weekday>/", views.day_edit, name="day_edit"),
    path("days/<int:weekday>/toggle/", views.day_toggle, name="day_toggle"),
    # تعبئة تلقائية لجدول اليوم
    path("days/<int:weekday>/autofill/", views.day_autofill, name="day_autofill"),
    path("days/<int:weekday>/clear/", views.day_clear, name="day_clear"),
    path("days/<int:weekday>/reindex/", views.day_reindex, name="day_reindex"),

    # الإعلانات
    path("announcements/", views.ann_list, name="ann_list"),
    path("announcements/new/", views.ann_create, name="ann_create"),
    path("announcements/<int:pk>/edit/", views.ann_edit, name="ann_edit"),
    path("announcements/<int:pk>/delete/", views.ann_delete, name="ann_delete"),

    # التميز
    path("excellence/", views.exc_list, name="exc_list"),
    path("excellence/new/", views.exc_create, name="exc_create"),
    path("excellence/<int:pk>/edit/", views.exc_edit, name="exc_edit"),
    path("excellence/<int:pk>/delete/", views.exc_delete, name="exc_delete"),

    # حصص الانتظار
    path("standby/", views.standby_list, name="standby_list"),
    path("standby/new/", views.standby_create, name="standby_create"),
    path("standby/<int:pk>/delete/", views.standby_delete, name="standby_delete"),
    path("standby/import/", views.standby_import, name="standby_import"),

    # الجدول الزمني
    path("timetable/day/", views.timetable_day_view, name="timetable_day"),
    path("timetable/week/", views.timetable_week_view, name="timetable_week"),
    path("timetable/export/", views.timetable_export_csv, name="timetable_export_csv"),

    # شاشات العرض
    path("screens/", views.screen_list, name="screen_list"),
    path("screens/new/", views.screen_create, name="screen_create"),
    path("screens/<int:pk>/delete/", views.screen_delete, name="screen_delete"),

    # بيانات المدرسة (الفصول/المواد/المعلمين)
    path("school-data/", views.school_data, name="school_data"),
    path("add_class", views.add_class, name="add_class"),
    path("delete_class/<int:pk>", views.delete_class, name="delete_class"),
    path("add_subject", views.add_subject, name="add_subject"),
    path("delete_subject/<int:pk>", views.delete_subject, name="delete_subject"),
    path("add_teacher", views.add_teacher, name="add_teacher"),
    path("delete_teacher/<int:pk>", views.delete_teacher, name="delete_teacher"),

    # API لالتقاط لقطة من بيانات العرض
    path("api/display/snapshot/", display_snapshot, name="display_snapshot"),

    # لوحة إدارة النظام (SaaS Admin Panel)
    path("admin-panel/", views.system_admin_dashboard, name="system_admin_dashboard"),

    # إدارة المدارس
    path("admin-panel/schools/", views.system_schools_list, name="system_schools_list"),
    path("admin-panel/schools/add/", views.system_school_create, name="system_school_create"),
    path("admin-panel/schools/<int:pk>/edit/", views.system_school_edit, name="system_school_edit"),
    path(
        "admin-panel/schools/<int:pk>/delete/",
        views.system_school_delete,
        name="system_school_delete",
    ),

    # إدارة المستخدمين
    path("admin-panel/users/", views.system_users_list, name="system_users_list"),
    path("admin-panel/users/add/", views.system_user_create, name="system_user_create"),
    path("admin-panel/users/<int:pk>/edit/", views.system_user_edit, name="system_user_edit"),
    path(
        "admin-panel/users/<int:pk>/delete/",
        views.system_user_delete,
        name="system_user_delete",
    ),

    # إدارة اشتراكات المدارس
    path(
        "admin-panel/subscriptions/",
        views.system_subscriptions_list,
        name="system_subscriptions_list",
    ),
    path(
        "admin-panel/subscriptions/add/",
        views.system_subscription_create,
        name="system_subscription_create",
    ),
    path(
        "admin-panel/subscriptions/<int:pk>/edit/",
        views.system_subscription_edit,
        name="system_subscription_edit",
    ),
    path(
        "admin-panel/subscriptions/<int:pk>/delete/",
        views.system_subscription_delete,
        name="system_subscription_delete",
    ),
    path("my-subscription/", views.my_subscription, name="my_subscription"),
   
    path(
    "no-school/",
    views.no_school,
    name="no_school",
),

]
