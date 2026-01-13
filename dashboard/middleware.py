# dashboard/middleware.py
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve, Resolver404
from django.utils import timezone

from subscriptions.utils import school_has_active_subscription


class SubscriptionRequiredMiddleware:
    """
    يتحقق أن المدرسة النشطة (request.school) لديها اشتراك فعال قبل دخول /dashboard/

    - يعمل فقط على /dashboard/
    - يستثني: login/logout/demo_login/my_subscription/switch_school
    - لا يطبق على superuser ولا على غير المسجلين
    - يمنع تكرار رسالة الخطأ في نفس الجلسة
    """

    EXEMPT_VIEWS = {
        "dashboard:login",
        "dashboard:logout",
        "dashboard:demo_login",
        "dashboard:my_subscription",
        "dashboard:switch_school",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.process_request(request)
        if response is not None:
            return response
        return self.get_response(request)

    def process_request(self, request):
        print(f"[DEBUG:middleware] user={getattr(request, 'user', None)} | path={getattr(request, 'path', None)} | is_authenticated={getattr(request.user, 'is_authenticated', None)} | is_superuser={getattr(request.user, 'is_superuser', None)}")
        path = request.path or ""

        if path.startswith("/static/") or path.startswith("/media/"):
            return None

        if not path.startswith("/dashboard/"):
            return None

        if not request.user.is_authenticated:
            return None

        # السماح الفوري للمستخدم الخارق (superuser) بدون أي تحقق آخر
        if getattr(request.user, "is_superuser", False):
            return None

        # موظف الدعم (Support group) لا يخضع لشرط اشتراك مدرسة
        try:
            if request.user.groups.filter(name="Support").exists():
                return None
        except Exception:
            pass

        try:
            match = resolve(request.path_info)
            view_name = match.view_name or ""
        except Resolver404:
            view_name = ""

        if view_name in self.EXEMPT_VIEWS:
            return None

        school = getattr(request, "school", None)
        if not school:
            # لا تمنع هنا حتى لا تعمل لوب؛
            # خلي الفيوهات تتعامل مع عدم وجود مدرسة عند الحاجة.
            return None

        today = timezone.localdate()
        has_active = school_has_active_subscription(school_id=school.id, on_date=today)

        if has_active:
            request.session.pop("sub_blocked_once", None)
            return None

        if not request.session.get("sub_blocked_once"):
            messages.error(request, "⚠️ اشتراك مدرستكم منتهي أو غير نشط. الرجاء مراجعة صفحة الاشتراك.")
            request.session["sub_blocked_once"] = True

        return redirect("dashboard:my_subscription")


class SupportDashboardOnlyMiddleware:
    """Restrict Support employees to dashboard only.

    Requirement:
    - Support group users should only see the system admin dashboard.
    - If they try to access any other URL, redirect them back.

    Notes:
    - Superusers are NOT restricted.
    - Static/media and display API endpoints are excluded.
    """

    ALLOWED_VIEW_NAMES = {
        "dashboard:system_admin_dashboard",
        "dashboard:login",
        "dashboard:logout",
        "dashboard:change_password",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = (getattr(request, "path", "") or "").strip()

        if not path:
            return self.get_response(request)

        # Always allow static/media and display API
        if path.startswith("/static/") or path.startswith("/media/") or path.startswith("/api/display/"):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return self.get_response(request)

        if getattr(user, "is_superuser", False):
            return self.get_response(request)

        try:
            is_support = user.groups.filter(name="Support").exists()
        except Exception:
            is_support = False

        if not is_support:
            return self.get_response(request)

        # Allow the dashboard home only.
        try:
            match = resolve(request.path_info)
            view_name = match.view_name or ""
        except Resolver404:
            view_name = ""

        if view_name in self.ALLOWED_VIEW_NAMES:
            return self.get_response(request)

        # For anything else, force back to the system dashboard.
        return redirect("dashboard:system_admin_dashboard")
