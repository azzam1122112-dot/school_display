from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from core.models import UserProfile, School


def manager_required(view_func):
    """
    ديكور لصلاحيات مدير المدرسة / المستخدم المرتبط بمدرسة معيّنة.

    - يضمن وجود UserProfile للمستخدم.
    - يضمن أن الـ Profile مرتبط بمدرسة.
    - يسمح للـ superuser دائمًا بالدخول (مع محاولة ربطه بمدرسة).
    - يسمح لأي مستخدم لديه profile.active_school.
    - يسمح لأعضاء مجموعة "Managers" (للتوافق مع أنظمة قديمة).
    """

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user

        # 1) التأكد من وجود ملف شخصي للمستخدم
        if not hasattr(user, "profile"):
            if user.is_superuser:
                # للـ superuser: إنشاء/جلب ملف شخصي وربطه بأول مدرسة إن وجدت
                first_school = School.objects.first()
                if first_school:
                    profile, _created = UserProfile.objects.get_or_create(user=user)
                    if profile.active_school is None:
                        profile.active_school = first_school
                        profile.schools.add(first_school)
                        profile.save()
                        messages.success(
                            request,
                            f"تم إنشاء ملف شخصي تلقائيًا وربطه بالمدرسة: {first_school.name}",
                        )
                    # نحدّث الكائن في الذاكرة
                    user.refresh_from_db()
                else:
                    messages.warning(
                        request,
                        "لا توجد مدارس في النظام. يرجى إنشاء مدرسة أولاً.",
                    )
                    return redirect("admin:core_school_add")
            else:
                # مستخدم عادي بدون ملف شخصي
                raise PermissionDenied("المستخدم ليس لديه ملف شخصي.")

        # 2) التأكد من أن الملف الشخصي مرتبط بمدرسة نشطة
        if not user.profile.active_school:
            # إذا كان لديه مدارس مرتبطة، عيّن أول واحدة كمدرسة نشطة تلقائيًا
            schools_qs = user.profile.schools.all()
            if schools_qs.exists():
                user.profile.active_school = schools_qs.first()
                user.profile.save(update_fields=["active_school"])
                messages.info(request, f"تم تعيين المدرسة النشطة تلقائيًا: {user.profile.active_school.name}")
            elif user.is_superuser:
                first_school = School.objects.first()
                if first_school:
                    user.profile.active_school = first_school
                    user.profile.schools.add(first_school)
                    user.profile.save()
                    messages.success(
                        request,
                        f"تم ربط حسابك بالمدرسة: {first_school.name}",
                    )
                else:
                    messages.warning(
                        request,
                        "لا توجد مدارس في النظام. يرجى إنشاء مدرسة أولاً.",
                    )
                    return redirect("admin:core_school_add")
            else:
                raise PermissionDenied("الملف الشخصي غير مرتبط بأي مدرسة.")


        # 3) الـ superuser لديه صلاحية الوصول دائمًا بعد ضمان الربط
        if user.is_superuser:
            return view_func(request, *args, **kwargs)

        # 4) أي مستخدم مرتبط بمدرسة نشطة يمتلك صلاحية المدير المدرسي
        if getattr(user, "profile", None) and user.profile.active_school:
            return view_func(request, *args, **kwargs)

        # 5) دعم قديم: مجموعة Managers
        if user.groups.filter(name="Managers").exists():
            return view_func(request, *args, **kwargs)

        # 6) في غير ذلك: لا يملك صلاحية
        raise PermissionDenied("ليست لديك صلاحية الوصول.")

    return _wrapped


def superadmin_required(view_func):
    """
    ديكور لصلاحيات مدير النظام (SaaS System Admin).

    - يسمح فقط للمستخدمين الذين لديهم is_superuser=True.
    - لا يشترط وجود مدرسة أو ملف شخصي (مناسب للوحة إدارة النظام المركزية).
    """

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_superuser:
            # لا يُسمح لغير مدير النظام
            raise PermissionDenied("هذه الصفحة مخصّصة لمدير النظام فقط.")
        return view_func(request, *args, **kwargs)

    return _wrapped
