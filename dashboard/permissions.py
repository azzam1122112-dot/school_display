from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from core.models import UserProfile, School

def manager_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        
        # Ensure user has a profile
        if not hasattr(user, 'profile'):
            if user.is_superuser:
                # Auto-create profile for superuser if a school exists
                first_school = School.objects.first()
                if first_school:
                    UserProfile.objects.create(user=user, school=first_school)
                    # Refresh user to access the new profile
                    user.refresh_from_db()
                    messages.success(request, f"تم إنشاء ملف شخصي تلقائيًا وربطه بالمدرسة: {first_school.name}")
                else:
                    messages.warning(request, "لا توجد مدارس في النظام. يرجى إنشاء مدرسة أولاً.")
                    return redirect('admin:core_school_add')
            else:
                raise PermissionDenied("المستخدم ليس لديه ملف شخصي.")

        # Ensure profile has a school
        if not user.profile.school:
            if user.is_superuser:
                first_school = School.objects.first()
                if first_school:
                    user.profile.school = first_school
                    user.profile.save()
                    messages.success(request, f"تم ربط حسابك بالمدرسة: {first_school.name}")
                else:
                    messages.warning(request, "لا توجد مدارس في النظام. يرجى إنشاء مدرسة أولاً.")
                    return redirect('admin:core_school_add')
            else:
                raise PermissionDenied("الملف الشخصي غير مرتبط بأي مدرسة.")

        # 1. Superuser always has access (now safe)
        if user.is_superuser:
            return view_func(request, *args, **kwargs)
            
        # 2. Check if user has a school profile
        if hasattr(user, 'profile') and user.profile.school:
             return view_func(request, *args, **kwargs)

        # 3. Legacy check for Managers group
        if user.groups.filter(name="Managers").exists():
            return view_func(request, *args, **kwargs)
            
        raise PermissionDenied("ليست لديك صلاحية الوصول.")
    return _wrapped
