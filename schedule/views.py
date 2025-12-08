from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from core.models import School
from .services import get_current_lessons
from django.shortcuts import render, get_object_or_404

from core.models import School
from schedule.models import SchoolSettings

def api_current_lessons(request, school_id):
    school = get_object_or_404(School, pk=school_id)
    settings = school.schedule_settings

    data = get_current_lessons(settings)
    return JsonResponse(data, safe=False)



def display_screen(request, school_id: int):
    school = get_object_or_404(School, pk=school_id)
    settings: SchoolSettings | None = getattr(school, "schedule_settings", None)

    # 1) كود الثيم المخزن في نموذج الإعدادات (default / boys / girls)
    settings_theme = "default"
    if settings and settings.theme:
        settings_theme = settings.theme

    # 2) خريطة التحويل إلى القيم التي يستعملها الـ CSS في شاشة العرض
    theme_map = {
        "default": "indigo",   # الثيم الافتراضي (أزرق/بنفسجي)
        "boys": "emerald",     # ثيم مدارس البنين (أخضر)
        "girls": "rose",       # ثيم مدارس البنات (وردي)
    }
    theme_slug = theme_map.get(settings_theme, "indigo")

    context = {
        "school_name": settings.name if settings else school.name,
        "logo_url": settings.logo_url if settings else "",
        "refresh_interval_sec": settings.refresh_interval_sec if settings else 60,
        "standby_scroll_speed": settings.standby_scroll_speed if settings else 0.8,
        "periods_scroll_speed": settings.periods_scroll_speed if settings else 0.5,
        "api_token": "",  # لو عندك توكن يمر من هنا
        "theme": theme_slug,   # 👈 أهم سطر
    }

    return render(request, "schedule/display.html", context)