# website/views.py
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from schedule.models import SchoolSettings

def health(request):
    return HttpResponse("School Display is running. 👍")

def display(request):
    settings_obj = SchoolSettings.objects.first()
    ctx = {
        "school_name": settings_obj.name if settings_obj else "مدرستنا",
        "logo_url": settings_obj.logo_url if settings_obj else None,
        "refresh_interval_sec": settings_obj.refresh_interval_sec if settings_obj else 30,
        "auto_dark_after_hour": settings_obj.auto_dark_after_hour if settings_obj else 18,
        "now_hour": timezone.localtime().hour,
        "theme": (settings_obj.theme if settings_obj else "indigo"),  # indigo, sky, emerald, rose ...
    }
    return render(request, "website/display.html", ctx)
from django.shortcuts import render

def home(request):
    # ببساطة يعرض القالب display.html
    return render(request, "website/display.html")
