# core/middleware.py
from __future__ import annotations

from typing import Optional
import re
import logging
import secrets
import hashlib
import json

from django.apps import apps
from django.db.models import Q
from django.http import JsonResponse
from django.conf import settings as dj_settings
from django.utils import timezone
from django.core.cache import cache


logger = logging.getLogger(__name__)


# ==========================================================
# Snapshot Edge Cache Middleware (Cloudflare)
# ==========================================================
class SnapshotEdgeCacheMiddleware:
    """Hard-enforce cache headers for /api/display/snapshot/*.

    هدفه Phase 1:
    - منع أي Set-Cookie أو Vary: Cookie على مسار snapshot (حتى لا يصبح CF-Cache-Status: DYNAMIC)
    - منع كاش المتصفح نهائيًا (Cache-Control: no-store)
    - السماح لـ Cloudflare Edge بالكاش القصير عبر Cloudflare-CDN-Cache-Control (افتراضيًا 10 ثواني)
    """

    SNAPSHOT_PREFIX = "/api/display/snapshot/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        path = getattr(request, "path", "") or ""
        if not (path == self.SNAPSHOT_PREFIX or path.startswith(self.SNAPSHOT_PREFIX)):
            return response

        # Only apply to GET requests for snapshot.
        if request.method != "GET":
            return response

        # 1) Never set cookies on snapshot.
        try:
            response.cookies.clear()
        except Exception:
            pass

        # 2) Never vary by Cookie on snapshot (but keep Accept-Encoding for compression).
        vary = response.get("Vary")
        if vary:
            parts = [p.strip() for p in vary.split(",") if p.strip()]
            parts = [p for p in parts if p.lower() != "cookie"]
            if parts:
                response["Vary"] = ", ".join(parts)
            else:
                try:
                    del response["Vary"]
                except Exception:
                    pass

        # 3) Cache policy.
        force_nocache = (request.GET.get("nocache") or "").strip().lower() in {"1", "true", "yes"}
        if force_nocache or response.status_code != 200:
            response["Cache-Control"] = "no-store"
            response["Cloudflare-CDN-Cache-Control"] = "no-store"
            return response

        try:
            edge_ttl = int(getattr(dj_settings, "DISPLAY_SNAPSHOT_EDGE_MAX_AGE", 10) or 10)
        except Exception:
            edge_ttl = 10
        edge_ttl = max(1, min(60, edge_ttl))

        # Browser: no-store. Cloudflare edge: cache for a short TTL.
        response["Cache-Control"] = "no-store"
        response["Cloudflare-CDN-Cache-Control"] = f"public, max-age={edge_ttl}"
        return response


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

        is_snapshot_path = path == "/api/display/snapshot/" or path.startswith("/api/display/snapshot/")

        if not path.startswith(self.API_PREFIX):
            return self.get_response(request)

        if path in self.NO_TOKEN_PATHS:
            return self.get_response(request)

        token = self._extract_token(request)
        if not token or not self.TOKEN_RE.match(token):
            resp = JsonResponse({"error": "Invalid display token"}, status=403)
            if is_snapshot_path:
                resp["Cache-Control"] = "no-store"
            return resp

        # ------------------------------------------------------------------
        # Performance: Search Redis First
        # ------------------------------------------------------------------
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        neg_key = f"display:token_neg:{token_hash}"
        map_key = f"display:token_map:{token_hash}"

        # 1. Negative Cache (Invalid Token)
        if cache.get(neg_key):
            resp = JsonResponse({"error": "Invalid or inactive display token (cached)"}, status=403)
            if is_snapshot_path:
                resp["Cache-Control"] = "no-store"
            return resp

        # 2. Positive Cache (Valid Token)
        cached_data = cache.get(map_key)
        screen = None
        DisplayScreen = apps.get_model("core", "DisplayScreen")
        School = apps.get_model("core", "School") # Might be needed

        if isinstance(cached_data, dict):
            # Reconstruct minimal objects to avoid DB
            try:
                screen = DisplayScreen()
                screen.id = cached_data["id"]
                screen.pk = cached_data["id"]
                screen.school_id = cached_data["school_id"]
                screen.bound_device_id = cached_data.get("bound_device_id")
                # Also attach a dummy school object if needed
                request.school = School()
                request.school.id = screen.school_id
                request.school.pk = screen.school_id
            except Exception:
                screen = None

        if not screen:
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
                
                # Cache Success
                cache_payload = {
                    "id": screen.pk,
                    "school_id": screen.school_id,
                    "bound_device_id": getattr(screen, "bound_device_id", None)
                }
                cache.set(map_key, cache_payload, timeout=86400) # 24 hours

                request.school = screen.school

            except DisplayScreen.DoesNotExist:
                # Cache Failure
                cache.set(neg_key, "1", timeout=60)
                resp = JsonResponse({"error": "Invalid or inactive display token"}, status=403)
                if is_snapshot_path:
                    resp["Cache-Control"] = "no-store"
                return resp
            except Exception:
                logger.exception("DisplayTokenMiddleware failed while fetching screen")
                resp = JsonResponse({"error": "Display token lookup failed"}, status=500)
                if is_snapshot_path:
                    resp["Cache-Control"] = "no-store"
                return resp

        request.display_screen = screen
        if not hasattr(request, "school") or not request.school:
             # Should be set above, but safe fallback (though caching dummy object avoids DB here)
             # If we are here from cache hit, request.school is a dummy.
             pass

        # ======================================================
        # ✅ Device Binding (منع مشاركة رابط الشاشة)
        #
        # ملاحظة (Phase 1 caching): مسار snapshot يجب ألا يرسل Set-Cookie حتى يكون قابل للكاش على Cloudflare.
        # لذلك نتجنب إنشاء/تعيين كوكي sd_device على snapshot.
        # ======================================================
        new_device_id: Optional[str] = None
        if not is_snapshot_path:
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
                            # ✅ Update Cache to reflect binding
                            try:
                                new_payload = {
                                    "id": screen.pk,
                                    "school_id": getattr(screen, "school_id", getattr(request.school, "pk", None)),
                                    "bound_device_id": bound
                                }
                                # Ensure we have a valid map number
                                if map_key:
                                    cache.set(map_key, new_payload, timeout=86400)
                            except Exception:
                                pass
                        else:
                            # تم ربطها من جهاز آخر قبلنا
                            try:
                                # Re-fetch from DB if concurrency issue
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
        if (not is_snapshot_path) and new_device_id and hasattr(response, "set_cookie"):
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
