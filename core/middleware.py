# core/middleware.py
from __future__ import annotations

import re
from typing import Optional

from django.apps import apps
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone


# ============================================================================
# 🔐 Display Token Middleware (Public Display API)
# ============================================================================

class DisplayTokenMiddleware:
    """
    Middleware خاص بشاشات العرض (Public Display).

    - مصادر التوكن:
      1) QueryString: ?token=
      2) Header: X-Display-Token
      3) Authorization: Display <token>

    - يضيف:
      request.display_screen
      request.display_token
      request.school

    ملاحظات:
    - المرجع الوحيد للموديل: core.DisplayScreen
    - يدعم توكن 32 و 64 hex (انتقالي)
    """

    API_PREFIX = "/api/display/"
    SNAPSHOT_PREFIX = "/api/display/snapshot"

    TOKEN_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")

    # مسارات عرض مسموحة بدون توكن (للاختبارات/التوافق)
    NO_TOKEN_PATHS = {
        "/api/display/ping/",
        "/api/display/today/",
        "/api/display/live/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def _extract_token(self, request) -> Optional[str]:
        token = request.GET.get("token")
        if token:
            return token.strip()

        token = request.headers.get("X-Display-Token")
        if token:
            return token.strip()

        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("display "):
            return auth.split(" ", 1)[1].strip()

        return None

    def _get_display_model(self):
        return apps.get_model("core", "DisplayScreen")

    def _model_has_field(self, model, field_name: str) -> bool:
        try:
            model._meta.get_field(field_name)
            return True
        except Exception:
            return False

    def __call__(self, request):
        path = request.path or ""

        # نطبّق الميدلوير فقط على API العرض
        if not path.startswith(self.API_PREFIX):
            return self.get_response(request)

        # مسارات مسموحة بدون توكن
        if path in self.NO_TOKEN_PATHS:
            return self.get_response(request)

        # snapshot غالبًا يتحقق داخل view أو قد يحمل التوكن داخل المسار
        if path.startswith(self.SNAPSHOT_PREFIX):
            return self.get_response(request)

        token = self._extract_token(request)
        if not token:
            return JsonResponse(
                {"error": "Display token is required."},
                status=403,
                json_dumps_params={"ensure_ascii": False},
            )

        if not self.TOKEN_RE.match(token):
            return JsonResponse(
                {"error": "Invalid display token format."},
                status=403,
                json_dumps_params={"ensure_ascii": False},
            )

        DisplayScreen = self._get_display_model()

        filters = {"token__iexact": token}
        if self._model_has_field(DisplayScreen, "is_active"):
            filters["is_active"] = True

        try:
            screen = DisplayScreen.objects.select_related("school").get(**filters)
        except DisplayScreen.DoesNotExist:
            return JsonResponse(
                {"error": "Invalid or inactive display token."},
                status=403,
                json_dumps_params={"ensure_ascii": False},
            )

        request.display_screen = screen
        request.display_token = token
        request.school = getattr(screen, "school", None)

        # تحديث آخر ظهور (كل 30 ثانية)
        now = timezone.now()
        update_field = (
            "last_seen_at"
            if self._model_has_field(DisplayScreen, "last_seen_at")
            else ("last_seen" if self._model_has_field(DisplayScreen, "last_seen") else None)
        )

        if update_field:
            last_val = getattr(screen, update_field, None)
            if not last_val or (now - last_val).total_seconds() > 30:
                DisplayScreen.objects.filter(pk=screen.pk).update(**{update_field: now})
                setattr(screen, update_field, now)

        return self.get_response(request)


# ============================================================================
# 🏫 Active School Middleware (Multi-School Guard) - النسخة النهائية
# ============================================================================

class ActiveSchoolMiddleware:
    """
    يضمن وجود مدرسة نشطة (active_school) للمستخدم قبل دخول الداشبورد.

    السلوك الصحيح:
    - إذا active_school موجود → يعيّن request.school ويمشي.
    - إذا active_school غير موجود لكن المستخدم مرتبط بمدرسة واحدة → يضبطها تلقائيًا ويكمل.
    - إذا مرتبط بأكثر من مدرسة → يوجه لصفحة اختيار المدرسة (إن وُجدت).
    - إذا غير مرتبط بأي مدرسة → صفحة no-school (إن وُجدت).
    - للـ API → يرجع JSON 403 بدل redirect.

    ✅ يمنع Redirect Loop:
    - يستثني صفحات no-school/select-school/login/logout/static/media/api وغيرها.
    - يستخدم reverse بشكل آمن مع fallback لمسارات ثابتة.
    """

    EXEMPT_PREFIXES = (
        "/admin/",
        "/static/",
        "/media/",
        "/favicon.ico",
        "/api/",                # API عام
        "/api/display/",        # API العرض
        "/dashboard/login/",
        "/dashboard/logout/",
        "/dashboard/select-school/",
        "/dashboard/no-school/",
    )

    # لوحات الداشبورد التي نحتاج تفعيل المدرسة لها
    PROTECT_PREFIXES = (
        "/dashboard/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""

        # 1) استثناء المسارات
        for p in self.EXEMPT_PREFIXES:
            if path.startswith(p):
                return self.get_response(request)

        # 2) لا نطبّق إلا على الداشبورد
        if not any(path.startswith(p) for p in self.PROTECT_PREFIXES):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # السوبر يدخل بدون قيود
        if getattr(user, "is_superuser", False):
            return self.get_response(request)

        profile = getattr(user, "profile", None)
        if not profile:
            return self._deny(request, reason="لا يوجد ملف مستخدم مرتبط بحسابك")

        # لو active_school موجود
        active_school = getattr(profile, "active_school", None)
        if active_school:
            request.school = active_school
            return self.get_response(request)

        # لو عنده مدارس مرتبطة
        schools_qs = getattr(profile, "schools", None)
        if schools_qs is None:
            return self._deny(request, reason="النظام لا يدعم المدارس المتعددة لهذا الحساب")

        # count() قد يكون ثقيل، لكنه هنا في لوحة التحكم فقط
        count = schools_qs.count()

        if count == 0:
            return self._deny(request, reason="لا توجد مدرسة مرتبطة بحسابك")

        if count == 1:
            # ✅ الحل الذكي: ضبط المدرسة النشطة تلقائيًا
            first = schools_qs.first()
            if first:
                profile.active_school = first
                profile.save(update_fields=["active_school"])
                request.school = first
                return self.get_response(request)

            return self._deny(request, reason="تعذر تحديد المدرسة المرتبطة")

        # أكثر من مدرسة → صفحة اختيار المدرسة
        return self._redirect_safe(request, "dashboard:select_school", "/dashboard/select-school/")

    def _deny(self, request, reason: str):
        # API: رد JSON
        if (request.path or "").startswith("/api/"):
            return JsonResponse(
                {"error": reason},
                status=403,
                json_dumps_params={"ensure_ascii": False},
            )

        # Web: صفحة no-school
        return self._redirect_safe(request, "dashboard:no_school", "/dashboard/no-school/")

    def _redirect_safe(self, request, url_name: str, fallback_path: str):
        try:
            return redirect(reverse(url_name))
        except NoReverseMatch:
            # fallback ثابت حتى لو URL name غير موجود
            return redirect(fallback_path)


# ============================================================================
# 🛡️ Security Headers Middleware
# ============================================================================

class SecurityHeadersMiddleware:
    """
    Middleware لإضافة رؤوس أمان أساسية.
    آمن للتطوير والإنتاج.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # لو تحتاج iframe فقط لشاشات العرض، لا تجعلها DENY عالميًا
        # لأن بعض المتصفحات/العرض قد تحتاج نفس النطاق.
        # الأفضل تركها للـ settings أو تقييدها حسب المسار.
        if not (request.path or "").startswith("/api/display/"):
            response.setdefault("X-Frame-Options", "SAMEORIGIN")

        return response
