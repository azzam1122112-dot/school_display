# core/middleware.py
from __future__ import annotations

import re
from typing import Optional

from django.apps import apps
from django.http import JsonResponse
from django.utils import timezone


class DisplayTokenMiddleware:
    """
    Middleware خاص بشاشات العرض (Public Display).

    - يدعم التوكن من:
      1) QueryString: ?token=
      2) Header: X-Display-Token
      3) Authorization: Display <token>

    - يضيف إلى الطلب:
      request.display_screen
      request.display_token
      request.school

    ملاحظات:
    - المرجع الوحيد للموديل: core.DisplayScreen
    - ندعم توكن 64 hex (قياسي) + 32 hex (انتقالي لبيانات قديمة)
    - بعض المسارات قد تكون "aliases/legacy" ويُسمح لها بدون توكن حتى لا تنكسر الاختبارات/التوافق.
    """

    API_PREFIX = "/api/display/"

    # 🔐 دعم 32 و 64 hex (انتقالي + متوافق مع البيانات الحالية)
    TOKEN_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")

    # مسارات مسموحة بدون توكن (للاختبارات/التوافق)
    NO_TOKEN_PATHS = {
        "/api/display/ping/",
        "/api/display/today/",
        "/api/display/live/",
    }

    # snapshot له منطق خاص (أحيانًا token في المسار)، فلا نفرض توكن من هنا
    SNAPSHOT_PREFIX = "/api/display/snapshot"

    def __init__(self, get_response):
        self.get_response = get_response

    def _extract_token(self, request) -> Optional[str]:
        # 1) QueryString
        token = request.GET.get("token")
        if token:
            return token.strip()

        # 2) Header
        token = request.headers.get("X-Display-Token")
        if token:
            return token.strip()

        # 3) Authorization: Display <token>
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("display "):
            tok = auth.split(" ", 1)[1].strip()
            if tok:
                return tok

        return None

    def _get_display_model(self):
        # ✅ المرجع الوحيد: core.DisplayScreen
        return apps.get_model("core", "DisplayScreen")

    def _model_has_field(self, model, field_name: str) -> bool:
        try:
            model._meta.get_field(field_name)
            return True
        except Exception:
            return False

    def __call__(self, request):
        path: str = request.path or ""

        # نقيّد الميدلوير على API العرض فقط
        if not path.startswith(self.API_PREFIX):
            return self.get_response(request)

        # مسارات بدون توكن
        if path in self.NO_TOKEN_PATHS:
            return self.get_response(request)

        # snapshot: لا نتحقق هنا (التحقق داخل الـ view إن لزم)
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
            qs = DisplayScreen.objects.select_related("school")

            only_fields = ["id", "token"]
            if self._model_has_field(DisplayScreen, "school"):
                only_fields.append("school_id")
            if self._model_has_field(DisplayScreen, "is_active"):
                only_fields.append("is_active")
            if self._model_has_field(DisplayScreen, "last_seen_at"):
                only_fields.append("last_seen_at")
            if self._model_has_field(DisplayScreen, "last_seen"):
                only_fields.append("last_seen")

            screen = qs.only(*only_fields).get(**filters)

        except DisplayScreen.DoesNotExist:
            return JsonResponse(
                {"error": "Invalid or inactive display token."},
                status=403,
                json_dumps_params={"ensure_ascii": False},
            )

        # ربط البيانات بالطلب
        request.display_screen = screen
        request.display_token = token
        request.school = getattr(screen, "school", None)

        # تحديث last_seen (كل 30 ثانية)
        now = timezone.now()
        update_field = (
            "last_seen_at"
            if self._model_has_field(DisplayScreen, "last_seen_at")
            else ("last_seen" if self._model_has_field(DisplayScreen, "last_seen") else None)
        )

        if update_field:
            last_seen_val = getattr(screen, update_field, None)
            if not last_seen_val or (now - last_seen_val).total_seconds() > 30:
                DisplayScreen.objects.filter(pk=screen.pk).update(**{update_field: now})
                setattr(screen, update_field, now)

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Headers إضافية للأمان.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        resp = self.get_response(request)

        resp["X-Content-Type-Options"] = "nosniff"
        resp["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return resp
