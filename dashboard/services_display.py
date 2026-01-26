import json
import time
import logging
from typing import Dict, Any, Optional

from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
from django.conf import settings

# استيراد المودلز (يتم تعديل المسارات حسب مشروعك الفعلي)
from core.models import School
from schedule.models import Period, Break, DutyAssignment, SchoolSettings
from notices.models import Announcement
# from excellence.models import HonorList # مثال

logger = logging.getLogger(__name__)

# مفاتيح Redis
KEY_PREFIX = "display"
TTL_SNAPSHOT = 60 * 60 * 24 * 7  # أسبوع (طالما الإدارة لم تعدل، تبقى البيانات)
TTL_TOKEN = 60 * 60 * 24        # يوم لتخزين التوكن في الكاش

def get_redis_connection():
    """
    استرجاع اتصال Redis الأصلي لاستخدام Pipeline
    """
    # نفترض استخدام django-redis، للوصول للعميل الأصلي
    try:
        return cache.client.get_client()
    except AttributeError:
        # Fallback for some cache backends or mock scenarios
        return cache

# ---------------------------------------------------------------------------
# 1. Builder Service
# ---------------------------------------------------------------------------

def build_school_snapshot(school_id: int) -> Dict[str, Any]:
    """
    يقوم ببناء قاموس ضخم يحتوي على كل ما تحتاجه الشاشة.
    يُستدعى فقط عند التغيير (Write-Heavy logic).
    """
    try:
        school = School.objects.get(pk=school_id)
    except School.DoesNotExist:
        logger.error(f"School {school_id} not found during build_snapshot")
        return {}

    # 1. الإعدادات الأساسية
    settings_obj = getattr(school, "schedule_settings", None)
    
    # 2. التوقيت والمنطقة
    now = timezone.localtime()
    
    # 3. الجدول الدراسي (Schedule)
    # نسحب كل الحرات/الفترات النشطة لهذا اليوم
    try:
        periods = Period.objects.filter(school=school, is_active=True).values(
            'id', 'name', 'start_time', 'end_time', 'type'
        )
    except Exception:
        periods = []
        logger.warning(f"Could not fetch periods for school {school_id}")
    
    # 4. التنبيهات (Alerts/Notices)
    try:
        active_notices = Announcement.objects.active_for_school(
            school=school, 
            now=now
        ).values('id', 'title', 'body', 'level')
    except Exception:
        active_notices = []

    # 5. الثيم والمظهر
    theme_config = {
        "theme_name": settings_obj.theme if settings_obj else "default",
        "primary_color": getattr(settings_obj, "primary_color", "#000000"),
        "logo_url": school.logo.url if school.logo else "",
        "scroll_speed": getattr(settings_obj, "standby_scroll_speed", 1.0)
    }

    # بناء الـ JSON النهائي
    snapshot = {
        "meta": {
            "school_id": school.id,
            "school_name": school.name,
            "generated_at": now.isoformat(),
            "timezone": str(timezone.get_current_timezone()),
            "day_key": now.strftime("%A").lower(), # sunday, monday...
            "server_timestamp": int(now.timestamp()), # للمزامنة الزمنية في المتصفح
        },
        "config": theme_config,
        "schedule": {
            "periods": list(periods),
            "breaks": [], # يمكن إضافتها بنفس الطريقة
            "mode": "normal" # or "exam", "ramadan"
        },
        "widgets": {
            "notices": list(active_notices),
            "weather": {"enabled": True, "city": school.city if hasattr(school, 'city') else ""},
            "honor_board": [], # يمكن سحب قائمة المتميزين
        }
    }

    return snapshot

# ---------------------------------------------------------------------------
# 2. Atomic Cache Writer
# ---------------------------------------------------------------------------

def cache_write_snapshot(school_id: int, snapshot: Dict[str, Any]) -> int:
    """
    يكتب الـ Snapshot ويزيد الإصدار (Version) بشكل ذري (Atomic).
    يعيد رقم الإصدار الجديد.
    """
    redis_client = get_redis_connection()
    
    version_key = f"{KEY_PREFIX}:school:{school_id}:version"
    data_key = f"{KEY_PREFIX}:school:{school_id}:snapshot"
    
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    try:
        # Check if we have a real redis client with pipeline support
        if hasattr(redis_client, 'pipeline'):
            pipeline = redis_client.pipeline()
            pipeline.incr(version_key)            # 1. زيادة الإصدار
            pipeline.set(data_key, snapshot_json) # 2. حفظ البيانات
            results = pipeline.execute()
            new_version = results[0]
        else:
            # Fallback for simple cache backends (not fully atomic but functional)
            new_version = redis_client.incr(version_key)
            redis_client.set(data_key, snapshot_json)
            
        logger.info(f"Snapshot updated for School {school_id}, New Version: {new_version}")
        return new_version
    except Exception as e:
        logger.error(f"Failed to write snapshot to cache: {e}")
        return 0

# ---------------------------------------------------------------------------
# 3. Read-Only Accessors (For Views)
# ---------------------------------------------------------------------------

def get_cached_school_version(school_id: int) -> int:
    """قراءة سريعة جداً للإصدار فقط"""
    v = cache.get(f"{KEY_PREFIX}:school:{school_id}:version")
    try:
        return int(v) if v else 0
    except (ValueError, TypeError):
        return 0

def get_cached_school_snapshot(school_id: int) -> Optional[str]:
    """قراءة الـ JSON الخام مباشرة من الكاش"""
    redis_client = get_redis_connection()
    key = f"{KEY_PREFIX}:school:{school_id}:snapshot"
    
    # Try raw get first if available to avoid decoding/encoding overhead
    if hasattr(redis_client, 'get'):
        data = redis_client.get(key)
        if data:
            return data.decode('utf-8') if isinstance(data, bytes) else data
    
    # Fallback to standard Django cache wrapper
    return cache.get(key)

def verify_token_cached(token: str) -> Optional[int]:
    """
    التحقق من التوكن عبر الكاش أولاً.
    إذا لم يوجد، نفحص DB مرة واحدة ثم نخزنه.
    """
    cache_key = f"{KEY_PREFIX}:token:{token}"
    
    # 1. Fast Path
    school_id = cache.get(cache_key)
    if school_id:
        return school_id
        
    # 2. Slow Path (Only on first run or cache eviction)
    # هذا المكان الوحيد الذي قد يلمس DB في تدفق القراءة
    try:
        # Simulation: In real code, import Token model and fetch
        # school = School.objects.get(token=token)
        # cache.set(cache_key, school.id, timeout=TTL_TOKEN)
        # return school.id
        return None 
    except Exception:
        return None
