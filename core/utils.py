# core/utils.py
from __future__ import annotations

import re
from typing import Optional, Tuple, Any

from django.apps import apps

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
        scr = (
            DisplayScreen.objects
            .select_related("school")
            .get(token__iexact=tok, is_active=True)
        )
        return scr, getattr(scr, "school", None)
    except Exception:
        return None, None
