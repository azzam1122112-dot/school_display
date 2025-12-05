from core.models import DisplayScreen

def validate_display_token(request):
    """
    Validates the display token from the request GET parameters.
    Returns the DisplayScreen instance if valid and active, otherwise None.
    """
    token = request.GET.get('token')
    if not token:
        return None
    
    try:
        screen = DisplayScreen.objects.select_related('school').get(token=token, is_active=True)
        return screen
    except DisplayScreen.DoesNotExist:
        return None
