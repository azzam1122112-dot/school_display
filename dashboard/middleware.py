from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import Resolver404, resolve
from django.utils import timezone

from subscriptions.utils import school_has_active_subscription


class SubscriptionRequiredMiddleware:
    """
    يتحقق من وجود اشتراك نشط للمدرسة النشطة للمستخدم (active_school).

    القواعد:
    - يعمل فقط على مسارات /dashboard/
    - يستثني: login/logout/demo_login/my_subscription/switch_school
    - لا يطبق على superuser ولا على غير المسجلين
    - يمنع تكرار رسالة الخطأ داخل نفس الجلسة
    """

    EXEMPT_VIEWS = {
        "dashboard:login",
        "dashboard:logout",
        "dashboard:demo_login",
        "dashboard:my_subscription",
        "dashboard:switch_school",
    }

    # احتياط: بعض المشاريع قد لا تُعيد view_name بدقة في بعض الحالات
    EXEMPT_PATH_PREFIXES = (
        "/dashboard/login/",
        "/dashboard/logout/",
        "/dashboard/demo-login/",
        "/dashboard/my-subscription/",
        "/dashboard/switch-school/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.process_request(request)
        if response is not None:
            return response
        return self.get_response(request)

    def process_request(self, request):
        path = request.path or ""

        # تجاهل الستاتيك والملفات
        if path.startswith("/static/") or path.startswith("/media/"):
            return None

        # يعمل فقط على الداشبورد
        if not path.startswith("/dashboard/"):
            return None

        # استثناءات بالمسار (احتياط)
        for p in self.EXEMPT_PATH_PREFIXES:
            if path.startswith(p):
                return None

        # يتطلب تسجيل دخول
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        # السوبر يوزر مستثنى
        if user.is_superuser:
            return None

        # استثناءات بالـ view_name
        try:
            match = resolve(request.path_info)
            view_name = (match.view_name or "").strip()
        except Resolver404:
            view_name = ""

        if view_name in self.EXEMPT_VIEWS:
            return None

        # جلب المدرسة النشطة
        profile = getattr(user, "profile", None)
        school = getattr(profile, "active_school", None)

        # لو ما فيه مدرسة نشطة:
        # - لا نكسر النظام
        # - نحاول توجيهه لاختيار مدرسة أو صفحة الاشتراك
        if school is None:
            # لو عنده مدارس في M2M، خلّه يختار
            if profile is not None:
                try:
                    if hasattr(profile, "schools") and profile.schools.exists():
                        return redirect("dashboard:switch_school")
                except Exception:
                    pass
            return redirect("dashboard:my_subscription")

        # تحقق الاشتراك
        today = timezone.localdate()
        try:
            has_active = school_has_active_subscription(school.id, on_date=today)
        except Exception:
            # لو حصل أي خطأ داخل utils لا نكسر الداشبورد بالكامل
            has_active = True

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
