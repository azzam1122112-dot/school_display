from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
from .models import SchoolSettings
from core.models import DisplayScreen

@receiver(post_save, sender=SchoolSettings)
def clear_display_cache_on_settings_change(sender, instance, **kwargs):
    """
    Clears the display context cache for all screens associated with a school
    when its SchoolSettings are updated.
    """
    school = instance.school
    if not school:
        return

    # Find all display screens linked to this school
    screens = DisplayScreen.objects.filter(school=school)
    
    # Invalidate the cache for each screen
    for screen in screens:
        cache_key = f"display_context_{screen.token}"
        cache.delete(cache_key)
