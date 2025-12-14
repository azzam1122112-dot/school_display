from __future__ import annotations

from functools import wraps
from typing import Callable, Any

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def _get_profile_model():
    return apps.get_model("core", "UserProfile")


def _get_or_create_profile(user):
    Profile = _get_profile_model()
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def _has_school_access(user) -> bool:
    """
    صلاحية إدارة لوحة المدرسة:
    - superuser دائمًا مسموح
    - وإلا: لازم يكون المستخدم مرتبط بمدرسة (schools) أو لديه active_school
    """
    if getattr(user, "is_superuser", False):
        return True

    profile = _get_or_create_profile(user)

    # لو عنده مدرسة نشطة
    if getattr(profile, "active_school_id", None):
        return True

    # لو عنده مدارس مرتبطة
    schools_mgr = getattr(profile, "schools", None)
    if schools_mgr is not None:
        try:
            return profile.schools.exists()
        except Exception:
            return False

    return False


def manager_required(view_func: Callable[..., Any]):
    """
    يمرر:
    - superuser
    - أو أي مستخدم مرتبط بمدرسة عبر UserProfile (schools/active_school)

    إذا ما عنده مدرسة: نوجهه لصفحة اختيار المدرسة بدل 403
    """
    @login_required(login_url="dashboard:login")
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user

        # superuser
        if getattr(user, "is_superuser", False):
            return view_func(request, *args, **kwargs)

        profile = _get_or_create_profile(user)

        # عنده active_school
        if getattr(profile, "active_school_id", None):
            return view_func(request, *args, **kwargs)

        # عنده مدارس لكن ما اختار active_school
        try:
            if profile.schools.exists():
                messages.info(request, "فضلاً اختر المدرسة النشطة أولاً.")
                return redirect("dashboard:select_school")
        except Exception:
            pass

        # ما عنده مدارس إطلاقًا
        raise PermissionDenied("حسابك غير مرتبط بأي مدرسة للوصول إلى لوحة التحكم.")

    return _wrapped


def superuser_required(view_func: Callable[..., Any]):
    """
    صفحات لوحة إدارة النظام (SaaS) للسوبر فقط.
    """
    @login_required(login_url="dashboard:login")
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request.user, "is_superuser", False):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied("هذه الصفحة مخصصة لمدير النظام فقط.")
    return _wrapped
