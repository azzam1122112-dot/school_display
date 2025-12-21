# core/middleware.py
from __future__ import annotations

from typing import Optional
import re
import logging
import secrets

from django.apps import apps
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone


logger = logging.getLogger(__name__)


# ==========================================================
# Display Token Middleware (API فقط)
# ==========================================================
class DisplayTokenMiddleware:
    """
    يحقن:
      - request.display_screen
      - request.school

    يدعم التوكن من:
      - /api/display/snapshot/<token>/
      - ?token=...
      - Header: X-Display-Token
      - Authorization: Display <token>
    """

    API_PREFIX = "/api/display/"
    TOKEN_RE = re.compile(r"^(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{64})$")
    SNAPSHOT_PATH_RE = re.compile(r"^/api/display/snapshot/(?P<token>[0-9a-fA-F]{32}|[0-9a-fA-F]{64})/?$")

    # مسارات لا تتطلب توكن (اختياري)
    NO_TOKEN_PATHS = {
        "/api/display/ping/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def _extract_token(self, request) -> Optional[str]:
        # 1) token في المسار (snapshot/<token>/)
        m = self.SNAPSHOT_PATH_RE.match(request.path or "")
        if m:
            return (m.group("token") or "").strip()

        # 2) token في QueryString
        t = (request.GET.get("token") or "").strip()
        if t:
            return t

        # 3) token في Header
        t = (request.headers.get("X-Display-Token") or "").strip()
        if t:
            return t

        # 4) Authorization: Display <token>
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("display "):
            return auth.split(" ", 1)[1].strip()

        return None

    def _pick_token_field(self, DisplayScreen) -> str:
        """
        مشاريعك السابقة ظهر فيها api_token أحيانًا.
        هنا ندعم أكثر من اسم حقل لتجنب FieldError.
        """
        candidates = ["token", "api_token", "display_token"]
        for f in candidates:
            try:
                DisplayScreen._meta.get_field(f)
                return f
            except Exception:
                continue
        raise LookupError("لم أجد حقل توكن مناسب في DisplayScreen (token/api_token/display_token).")

    def __call__(self, request):
        path = request.path or ""

        if not path.startswith(self.API_PREFIX):
            return self.get_response(request)

        if path in self.NO_TOKEN_PATHS:
            return self.get_response(request)

        token = self._extract_token(request)
        if not token or not self.TOKEN_RE.match(token):
            return JsonResponse({"error": "Invalid display token"}, status=403)

        DisplayScreen = apps.get_model("core", "DisplayScreen")

        token_field = self._pick_token_field(DisplayScreen)
        lookup = {f"{token_field}__iexact": token}

        # is_active اختياري حسب موديلك
        try:
            DisplayScreen._meta.get_field("is_active")
            lookup["is_active"] = True
        except Exception:
            pass

        try:
            screen = DisplayScreen.objects.select_related("school").get(**lookup)
        except DisplayScreen.DoesNotExist:
            return JsonResponse({"error": "Invalid or inactive display token"}, status=403)
        except Exception:
            logger.exception("DisplayTokenMiddleware failed while fetching screen")
            return JsonResponse({"error": "Display token lookup failed"}, status=500)

        request.display_screen = screen
        request.school = screen.school

        # ======================================================
        # ✅ Device Binding (منع مشاركة رابط الشاشة)
        #    لو لم يوجد كوكي للجهاز ننشئ واحدًا تلقائيًا
        # ======================================================
        new_device_id: Optional[str] = None
        device_id = (request.COOKIES.get("sd_device") or "").strip()
        if not device_id:
            try:
                new_device_id = secrets.token_hex(16)
                device_id = new_device_id
                # حتى ترى الـ view نفس الـ id في نفس الطلب
                request.COOKIES["sd_device"] = device_id
            except Exception:
                device_id = ""

        if device_id:
            has_binding_fields = True
            try:
                DisplayScreen._meta.get_field("bound_device_id")
                DisplayScreen._meta.get_field("bound_at")
            except Exception:
                has_binding_fields = False

            if has_binding_fields:
                bound = (getattr(screen, "bound_device_id", None) or "").strip()
                if not bound:
                    updated = (
                        DisplayScreen.objects.filter(pk=screen.pk)
                        .filter(Q(bound_device_id__isnull=True) | Q(bound_device_id=""))
                        .update(bound_device_id=device_id, bound_at=timezone.now())
                    )
                    if updated:
                        bound = device_id
                    else:
                        # تم ربطها من جهاز آخر قبلنا
                        try:
                            screen = DisplayScreen.objects.select_related("school").get(pk=screen.pk)
                            request.display_screen = screen
                            request.school = screen.school
                            bound = (getattr(screen, "bound_device_id", None) or "").strip()
                        except Exception:
                            bound = bound

                if bound and bound != device_id:
                    return JsonResponse(
                        {
                            "error": "screen_bound",
                            "message": "هذه الشاشة مرتبطة بجهاز آخر. قم بفصل الجهاز من لوحة التحكم لتفعيلها على جهاز جديد.",
                        },
                        status=403,
                    )

        # تحديث last_seen_at إن كان موجودًا
        now = timezone.now()
        try:
            DisplayScreen._meta.get_field("last_seen_at")
            last_seen = getattr(screen, "last_seen_at", None)
            if (last_seen is None) or ((now - last_seen).total_seconds() > 30):
                DisplayScreen.objects.filter(pk=screen.pk).update(last_seen_at=now)
        except Exception:
            pass

        response = self.get_response(request)
        if new_device_id and hasattr(response, "set_cookie"):
            try:
                # كوكي طويل المدى للجهاز (٥ سنوات تقريبًا)
                response.set_cookie(
                    "sd_device",
                    new_device_id,
                    max_age=60 * 60 * 24 * 365 * 5,
                    samesite="Lax",
                )
            except Exception:
                pass

        return response


# ==========================================================
# Active School Context (Context ONLY)
# ==========================================================
class ActiveSchoolMiddleware:
    """
    ✅ يحدد request.school للمستخدم المسجل (مدرسته النشطة)
    ❌ لا Redirect
    ❌ لا منع دخول

    مهم: لا يطغى على request.school إذا كان محدد مسبقًا (مثل display API).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # لا تكتب فوق request.school إذا موجودة
        if not hasattr(request, "school"):
            request.school = None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # لو سبق وتحددّت school من Middleware آخر، اتركها
        if getattr(request, "school", None) is not None:
            return self.get_response(request)

        profile = getattr(user, "profile", None)
        if not profile:
            return self.get_response(request)

        # عيّن active_school تلقائيًا عند عدم وجودها
        try:
            if not getattr(profile, "active_school_id", None) and profile.schools.exists():
                profile.active_school = profile.schools.first()
                profile.save(update_fields=["active_school"])
        except Exception:
            return self.get_response(request)

        request.school = getattr(profile, "active_school", None)
        return self.get_response(request)


# ==========================================================
# Security Headers
# ==========================================================
class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
