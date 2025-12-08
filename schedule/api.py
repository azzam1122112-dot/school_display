from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from core.models import School
from .services import get_current_lessons


def api_current_lessons(request, school_id):
    school = get_object_or_404(School, id=school_id)

    if not hasattr(school, "schedule_settings"):
        return JsonResponse({
            "error": "No schedule settings found for this school."
        }, status=404)

    data = get_current_lessons(school.schedule_settings)
    return JsonResponse(data, safe=False)
