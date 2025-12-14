# هذا الديكوريتر يجب أن يكون موجودًا في dashboard/decorators.py
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

def manager_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request.user, 'is_manager') or not request.user.is_manager:
            raise PermissionDenied("يجب أن تكون مديرًا للوصول إلى هذه الصفحة.")
        return view_func(request, *args, **kwargs)
    return user_passes_test(lambda u: hasattr(u, 'is_manager') and u.is_manager)(view_func)
