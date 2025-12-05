# website/views.py
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from core.models import DisplayScreen
from schedule.models import SchoolSettings

def health(request):
    return HttpResponse("School Display is running. 👍")

def display(request):
    return home(request)

def home(request):
    token = request.GET.get('token')
    settings_obj = None
    effective_token = token

    if token:
        try:
            screen = DisplayScreen.objects.select_related('school').get(token=token, is_active=True)
            settings_obj = SchoolSettings.objects.filter(school=screen.school).first()
        except DisplayScreen.DoesNotExist:
            pass

    # Fallback: If no token or invalid, try to get the first school (Legacy/Dev mode)
    if not settings_obj:
        settings_obj = SchoolSettings.objects.first()
        # If we found a default school but have no token, try to find a valid token for it
        if settings_obj and not effective_token:
            # Find a screen for this school (or global screen if school is None)
            screen = DisplayScreen.objects.filter(school=settings_obj.school, is_active=True).first()
            if screen:
                effective_token = screen.token
            else:
                # Create a temporary/default screen if none exists, to allow the display to work
                # This is important for the "first run" experience
                try:
                    screen = DisplayScreen.objects.create(
                        school=settings_obj.school,
                        name="Default Display",
                        is_active=True
                    )
                    effective_token = screen.token
                except Exception:
                    pass

    ctx = {
        "school_name": settings_obj.name if settings_obj else "مدرستنا",
        "logo_url": settings_obj.logo_url if settings_obj else None,
        "refresh_interval_sec": settings_obj.refresh_interval_sec if settings_obj else 30,
        "standby_scroll_speed": settings_obj.standby_scroll_speed if settings_obj else 0.8,
        "now_hour": timezone.localtime().hour,
        "theme": (settings_obj.theme if settings_obj else "indigo"),
        "api_token": effective_token,  # Pass the token to the template
    }
    return render(request, "website/display.html", ctx)
