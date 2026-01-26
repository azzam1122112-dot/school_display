import logging
import time
from django.http import HttpResponse, JsonResponse, HttpResponseNotModified
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .services_display import (
    get_cached_school_version, 
    get_cached_school_snapshot_gz, 
    verify_token_cached,
    build_school_snapshot,
    cache_write_snapshot,
    acquire_build_lock,
    release_build_lock
)

logger = logging.getLogger("dashboard.api")

def _authenticate(request):
    token = request.GET.get('token')
    if not token:
        auth = request.headers.get('Authorization')
        if auth and auth.startswith('Bearer '):
            token = auth.split(' ')[1]
            
    if not token:
        return None
    
    return verify_token_cached(token)

@require_GET
@csrf_exempt
def display_status(request):
    """
    GET /api/display/status/?token=...&v=105
    High-Frequency Polling Endpoint.
    """
    # 1. Rate Limit Check (Optional simple implementation)
    # يمكن استخدام Redis incr لعمل Rate Limit بسيط لكل IP
    
    # 2. Authenticate (Cached)
    school_id = _authenticate(request)
    if not school_id:
        return JsonResponse({"error": "Invalid Token"}, status=403)

    # 3. Check Version (Redis In-Memory)
    try:
        client_version = int(request.GET.get('v', '0'))
    except ValueError:
        client_version = 0

    server_version = get_cached_school_version(school_id)
    
    # إذا لم يكن هناك إصدار (0)، فهذا يعني أن الكاش فارغ ويحتاج بناء (Cold Start)
    if server_version == 0:
        pass # سيتم معالجته عند طلب الـ snapshot

    if client_version > 0 and client_version == server_version:
        # Metric: Client is up-to-date
        logger.info(f"METRIC_STATUS: School[{school_id}] | 304 Not Modified | Ver:{server_version}")
        return HttpResponseNotModified() # 304 - Bandwidth Saver

    # Metric: Client out-of-date
    logger.info(f"METRIC_STATUS: School[{school_id}] | 200 Update Required | Client:{client_version} -> Server:{server_version}")
    
    return JsonResponse({
        "status": "outdated",
        "current_version": server_version,
        "fetch_required": True
    })

@require_GET
@csrf_exempt
def display_snapshot(request):
    """
    GET /api/display/snapshot/?token=...
    Returns GZipped JSON.
    """
    school_id = _authenticate(request)
    if not school_id:
        return JsonResponse({"error": "Invalid Token"}, status=403)

    # 1. Fetch GZipped Data
    gz_data = get_cached_school_snapshot_gz(school_id)

    if not gz_data:
        # Cache Miss / Cold Start Strategy
        # نحاول البناء الآن (Synchronous fallback) ولكن مع Lock لمنع التكرار
        if acquire_build_lock(school_id):
            logger.info(f"Cache miss for School {school_id}. Triggering immediate build.")
            try:
                snapshot = build_school_snapshot(school_id)
                if snapshot:
                    cache_write_snapshot(school_id, snapshot)
                    # إعادة القراءة بعد البناء
                    gz_data = get_cached_school_snapshot_gz(school_id)
            finally:
                release_build_lock(school_id)
        else:
            # هناك عملية بناء جارية من طلب آخر
            # نطلب من العميل الانتظار قليلاً (Retry-After)
            response = JsonResponse({"error": "Building data..."}, status=503)
            response["Retry-After"] = 3
            return response

    if not gz_data:
        # إذا فشل البناء تماماً
        return JsonResponse({"error": "Data unavailable"}, status=500)

    # 2. Return Compressed
    # معظم المتصفحات والعملاء يدعمون gzip تلقائياً إذا تم تمرير الهيدر
    size_bytes = len(gz_data)
    logger.info(f"METRIC_SNAPSHOT: School[{school_id}] | Size: {size_bytes} bytes | GZIP")
    
    response = HttpResponse(gz_data, content_type="application/json")
    response["Content-Encoding"] = "gzip"
    response["Vary"] = "Accept-Encoding"
    # Content-Length مهم ليعرف العميل التقدم
    response["Content-Length"] = len(gz_data)
    
    return response
