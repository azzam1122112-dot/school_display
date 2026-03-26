from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from core.models import School
from core.utils import validate_display_token
from .services import get_current_lessons


@require_GET
def api_current_lessons(request, school_id):
    screen, school = validate_display_token(request)
    if not screen or not school:
        return JsonResponse({"detail": "Forbidden"}, status=403)
    if school.id != int(school_id):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    if not hasattr(school, "schedule_settings"):
        return JsonResponse({
            "error": "No schedule settings found for this school."
        }, status=404)

    data = get_current_lessons(school.schedule_settings)
    return JsonResponse(data, safe=False)
