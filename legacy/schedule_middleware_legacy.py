# schedule/middleware.py
"""
Deprecated:
هذا الملف موجود فقط للتوافق القديم.
المرجع الرسمي الآن:
    core.middleware.DisplayTokenMiddleware
    core.middleware.SecurityHeadersMiddleware
"""
from core.middleware import DisplayTokenMiddleware, SecurityHeadersMiddleware

__all__ = ["DisplayTokenMiddleware", "SecurityHeadersMiddleware"]
