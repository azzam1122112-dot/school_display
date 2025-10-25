from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

def manager_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = request.user
        # شرط: مستخدم نشط + ضمن مجموعة Managers أو superuser
        if user.is_superuser or user.groups.filter(name="Managers").exists():
            return view_func(request, *args, **kwargs)
        raise PermissionDenied("ليست لديك صلاحية الوصول.")
    return _wrapped
