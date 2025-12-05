from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

def manager_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        
        # 1. Superuser always has access
        if user.is_superuser:
            return view_func(request, *args, **kwargs)
            
        # 2. Check if user has a school profile
        # نتحقق من وجود ملف مستخدم مرتبط بمدرسة
        if hasattr(user, 'profile') and user.profile.school:
             return view_func(request, *args, **kwargs)

        # 3. Legacy check for Managers group
        if user.groups.filter(name="Managers").exists():
            return view_func(request, *args, **kwargs)
            
        raise PermissionDenied("ليست لديك صلاحية الوصول.")
    return _wrapped
