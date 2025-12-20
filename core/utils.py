# core/utils.py
from __future__ import annotations

import re
from typing import Optional, Tuple, Any

from django.apps import apps

from core.screen_limits import enforce_school_screen_limit

# ✅ نسمح بـ 64 hex (القياسي) + 32 hex (دعم انتقال لبيانات قديمة)
TOKEN_RE = re.compile(r"^(?:[0-9a-fA-F]{64}|[0-9a-fA-F]{32})$")


def _get_core_display_model():
    """
    المرجع الوحيد: core.DisplayScreen
    """
    return apps.get_model("core", "DisplayScreen")


def validate_display_token(request, token: Optional[str] = None):
    """
    ✅ يرجع: (screen, school) أو (None, None)

    مصادر التوكن:
    - request.display_screen (إن وُجد من middleware)
    - token parameter
    - query: ?token=
    - header: X-Display-Token
    - Authorization: Display <token>
    """
    # 0) لو middleware ربط الشاشة مسبقًا
    screen = getattr(request, "display_screen", None)
    if screen is not None:
        return screen, getattr(screen, "school", None)

    # 1) استخراج التوكن
    tok = (token or "").strip()
    if not tok:
        tok = (request.GET.get("token") or "").strip()
    if not tok:
        tok = (request.headers.get("X-Display-Token") or "").strip()
    if not tok:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("display "):
            tok = auth.split(" ", 1)[1].strip()

    if not tok or not TOKEN_RE.match(tok):
        return None, None

    DisplayScreen = _get_core_display_model()

    # 2) جلب الشاشة من core فقط
    try:
        # Fetch regardless of is_active so we can enforce the limit and potentially re-enable
        # a previously auto-disabled screen after renewal.
        scr_any = (
            DisplayScreen.objects
            .select_related("school")
            .filter(token__iexact=tok)
            .first()
        )
        if not scr_any:
            return None, None

        school = getattr(scr_any, "school", None)
        if school is not None:
            enforce_school_screen_limit(getattr(school, "id", None) or 0)

        scr = (
            DisplayScreen.objects
            .select_related("school")
            .filter(pk=scr_any.pk, is_active=True)
            .first()
        )
        if not scr:
            return None, None
        return scr, getattr(scr, "school", None)
    except Exception:
        return None, None
