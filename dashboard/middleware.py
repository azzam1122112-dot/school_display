from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve, Resolver404
from django.utils import timezone

from subscriptions.utils import school_has_active_subscription


class SubscriptionRequiredMiddleware:
    """
    يتحقق من أن المدرسة المرتبطة بالمستخدم لديها اشتراك نشط.

    - يعمل فقط على /dashboard/
    - يستثني: login/logout/demo_login/my_subscription
    - لا يطبق على superuser ولا على غير المسجلين
    - يمنع تكرار رسائل الخطأ في نفس الجلسة
    """

    EXEMPT_VIEWS = {
        "dashboard:login",
        "dashboard:logout",
        "dashboard:demo_login",
        "dashboard:my_subscription",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.process_request(request)
        if response is not None:
            return response
        return self.get_response(request)

    def process_request(self, request):
        path = request.path

        if path.startswith("/static/") or path.startswith("/media/"):
            return None

        if not path.startswith("/dashboard/"):
            return None

        if not request.user.is_authenticated:
            return None

        if request.user.is_superuser:
            return None

        try:
            match = resolve(request.path_info)
            view_name = match.view_name or ""
        except Resolver404:
            view_name = ""

        if view_name in self.EXEMPT_VIEWS:
            return None

        profile = getattr(request.user, "profile", None)
        school = getattr(profile, "school", None)
        if school is None:
            return None

        today = timezone.localdate()
        has_active = school_has_active_subscription(school.id, on_date=today)

        if has_active:
            # لو كان في السابق مرفوض ثم تجدد الاشتراك، نمسح الفلاج
            request.session.pop("sub_blocked_once", None)
            return None

        # منع تكرار الرسالة في كل request
        if not request.session.get("sub_blocked_once"):
            messages.error(
                request,
                "⚠️ اشتراك مدرستكم منتهي أو ملغي. الرجاء مراجعة تفاصيل الاشتراك.",
            )
            request.session["sub_blocked_once"] = True

        return redirect("dashboard:my_subscription")
