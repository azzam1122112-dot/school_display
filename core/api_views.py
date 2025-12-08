from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt

@require_GET
@csrf_exempt
def ping(request):
    return JsonResponse({"status": "ok"}, status=200)
