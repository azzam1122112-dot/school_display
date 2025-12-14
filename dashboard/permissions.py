# dashboard/permissions.py
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from core.models import UserProfile, School


def _pick_default_school() -> School | None:
    """
    اختيار مدرسة افتراضية:
    1) أول مدرسة نشطة
    2) وإلا أول مدرسة موجودة
    """
    return (
        School.objects.filter(is_active=True).order_by("id").first()
        or School.objects.order_by("id").first()
    )


def _ensure_profile_and_school(request):
    """
    يضمن:
    - وجود UserProfile
    - وجود active_school إن أمكن
    - إضافة active_school إلى schools (M2M)
    يرجع: (profile, active_school_or_none)
    """
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # لو لديه active_school: تأكد أنها ضمن schools
    if profile.active_school_id:
        if not profile.schools.filter(id=profile.active_school_id).exists():
            profile.schools.add(profile.active_school_id)
        return profile, profile.active_school

    # لو لا يملك active_school: حاول من المدارس المرتبطة
    school = profile.schools.order_by("id").first()
    if school:
        profile.active_school = school
        profile.save(update_fields=["active_school"])
        return profile, school

    # لو لا يملك schools: اختر مدرسة افتراضية من النظام (نشطة/أول مدرسة)
    school = _pick_default_school()
    if school:
        profile.schools.add(school)
        profile.active_school = school
        profile.save(update_fields=["active_school"])
        return profile, school

    return profile, None


def manager_required(view_func):
    """
    ديكور لصلاحيات مدير المدرسة / المستخدم المرتبط بمدرسة.

    ✅ المنطق المعتمد (متوافق مع النظام الجديد):
    - يضمن وجود UserProfile دائمًا.
    - يضمن وجود active_school إن أمكن.
    - السوبر يوزر مسموح دائمًا.
    - أي مستخدم لديه profile.active_school مسموح له (نمط "مدير مدرسة" الحالي).
    - توافق خلفي: مجموعة Managers مسموح لها أيضًا.
    - إذا لا توجد مدارس بالنظام: توجيه لصفحة إضافة مدرسة (للسوبر فقط) أو منع دخول.
    """

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user

        profile, school = _ensure_profile_and_school(request)

        # لا توجد مدارس إطلاقًا
        if school is None:
            if user.is_superuser:
                messages.warning(
                    request,
                    "لا توجد مدارس في النظام. يرجى إنشاء مدرسة أولاً.",
                )
                return redirect("admin:core_school_add")
            raise PermissionDenied("لا توجد مدارس في النظام أو لا تملك مدرسة نشطة.")

        # السوبر يوزر: دخول دائمًا بعد ضمان الربط
        if user.is_superuser:
            return view_func(request, *args, **kwargs)

        # أي مستخدم لديه مدرسة نشطة = مسموح
        if getattr(profile, "active_school_id", None):
            return view_func(request, *args, **kwargs)

        # توافق خلفي: مجموعة Managers
        if user.groups.filter(name="Managers").exists():
            return view_func(request, *args, **kwargs)

        raise PermissionDenied("ليست لديك صلاحية الوصول.")

    return _wrapped


def superadmin_required(view_func):
    """
    ديكور لصلاحيات مدير النظام (SaaS System Admin).

    - يسمح فقط للمستخدمين الذين لديهم is_superuser=True.
    - لا يشترط وجود مدرسة أو ملف شخصي.
    """

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied("هذه الصفحة مخصّصة لمدير النظام فقط.")
        return view_func(request, *args, **kwargs)

    return _wrapped
