from __future__ import annotations

import logging

from django.http import HttpResponseForbidden
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.utils.cache import add_never_cache_headers


logger = logging.getLogger(__name__)


def csrf_failure(request, reason="", template_name=None):
    path = getattr(request, "path", "") or ""
    method = getattr(request, "method", "") or ""
    origin = (request.headers.get("Origin") or "").strip()
    referer = (request.META.get("HTTP_REFERER") or "").strip()

    try:
        host = request.get_host()
    except Exception:
        host = ""

    try:
        secure = bool(request.is_secure())
    except Exception:
        secure = False

    try:
        user_id = getattr(getattr(request, "user", None), "pk", None)
    except Exception:
        user_id = None

    logger.warning(
        "csrf_failure path=%s method=%s host=%s origin=%s referer=%s secure=%s user_id=%s reason=%s",
        path,
        method,
        host,
        origin,
        referer,
        secure,
        user_id,
        str(reason or "")[:200],
    )

    view_name = ""
    try:
        view_name = getattr(getattr(request, "resolver_match", None), "view_name", "") or ""
    except Exception:
        view_name = ""

    if view_name == "dashboard:login" or path.rstrip("/") == "/dashboard/login":
        try:
            rotate_token(request)
        except Exception:
            pass
        get_token(request)
        response = render(
            request,
            "dashboard/login.html",
            {
                "next": (request.POST.get("next") or request.GET.get("next") or "").strip(),
                "csrf_retry": True,
                "csrf_failure_reason": "انتهت صلاحية جلسة الحماية لهذه الصفحة أو تم استخدام صفحة دخول مخزنة مؤقتًا. تم توليد رمز جديد، أعد المحاولة الآن.",
            },
            status=403,
        )
        add_never_cache_headers(response)
        response["X-CSRF-Failure"] = "1"
        return response

    response = HttpResponseForbidden("CSRF verification failed.")
    add_never_cache_headers(response)
    response["X-CSRF-Failure"] = "1"
    return response