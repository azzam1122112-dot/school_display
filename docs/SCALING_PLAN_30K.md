# خطة التوسع التدريجي: من الوضع الحالي إلى 30,000 شاشة متزامنة

> **التاريخ:** يونيو 2025  
> **الحالة الحالية:** ~100-500 شاشة مريحة، الحد الأقصى ~1,000-2,000  
> **الهدف:** 30,000 شاشة متزامنة بأداء مستقر

---

## ملخص المراحل

| المرحلة | الهدف | التكلفة | الشاشات |
|---------|------|---------|---------|
| **المرحلة 1** | تحسين الكود (بدون تكلفة) | $0 | 500 → 2,000 |
| **المرحلة 2** | CDN + Edge Caching | ~$0 (Cloudflare مجاني) | 2,000 → 5,000 |
| **المرحلة 3** | إدارة WebSocket + اتصالات | ~$7/شهر (Redis upgrade) | 5,000 → 10,000 |
| **المرحلة 4** | بنية تحتية + Auto-scaling | ~$50-150/شهر | 10,000 → 30,000 |

---

## تحليل الاختناقات الحالية

### العنق الزجاجي #1: Thundering Herd (شدة عالية)
- **المشكلة:** TTL الكاش = 30 ثانية، Polling كل 20 ثانية → كل الشاشات تتزامن عند انتهاء الكاش
- **التأثير عند 30,000 شاشة:** ~1,000 stampede/يوم مع 200-300ms spike لكل واحد

### العنق الزجاجي #2: عدد Workers (شدة عالية)
- **المشكلة:** 2 workers فقط، كل snapshot rebuild يستغرق 200-600ms
- **التأثير:** عند 1% cache miss = 300 rebuild كل 20 ثانية = 90 ثانية معالجة (مستحيل على 2 workers)

### العنق الزجاجي #3: Redis Memory (شدة متوسطة)
- **المشكلة:** Redis Starter = 25MB → كل اتصال WS ≈ 50-100KB Redis memory
- **التأثير:** ~250-500 WS connection قبل نفاد الذاكرة

### العنق الزجاجي #4: Snapshot Build Cost (شدة متوسطة)
- **المشكلة:** 6-8 DB queries لكل rebuild → 200-600ms
- **التأثير:** DB connections تنفد عند concurrent rebuilds

---

## المرحلة 1: تحسينات الكود (تكلفة = $0)

> **الهدف:** رفع Cache Hit Rate من ~70% إلى ~95%+  
> **الشاشات:** 500 → 2,000  
> **المدة:** يوم واحد

### 1.1 رفع Active TTL الافتراضي

**الملف:** `render.yaml` (متغيرات البيئة)

```
DISPLAY_SNAPSHOT_ACTIVE_TTL=45        # كان 30
DISPLAY_SNAPSHOT_TTL_JITTER_SEC=15    # كان 10
DISPLAY_SNAPSHOT_ACTIVE_TTL_MAX=60    # يبقى 60
```

**لماذا آمن؟** العميل يعتمد على `dayEngine` للتحولات الزمنية محلياً. الـ snapshot هو مرجع للبيانات فقط (إعلانات، جدول حصص) وليس للتوقيت.

**التأثير:** 
- TTL الفعلي = 45 + jitter(0-15) = 45-60 ثانية
- Polling كل 20 ثانية → 2-3 polls تُخدَم من الكاش = hit rate ~66-75% (بدلاً من ~50%)
- مع WS المُفعّل: polling كل 300 ثانية → hit rate ~99%+

### 1.2 تفعيل SNAPSHOT_STEADY_CACHE_V2

**الملف:** `render.yaml`

```
SNAPSHOT_STEADY_CACHE_V2=True         # كان False
```

**التأثير:** يُفعّل `DISPLAY_SNAPSHOT_ACTIVE_TTL_SAFE_MIN=30` كحد أدنى آمن، يمنع الكاش من الانتهاء أسرع من دورة الـ polling.

### 1.3 رفع School-Level Snapshot TTL

**الملف:** `render.yaml`

```
SCHOOL_SNAPSHOT_TTL=1800              # كان 900 (15 دقيقة → 30 دقيقة)
```

**لماذا؟** الـ school snapshot مشترك بين كل شاشات نفس المدرسة → كل ما زاد TTL، قل عدد الـ rebuilds.

### 1.4 تحسين Stale Fallback (تغيير كود)

**الملف:** `schedule/api_views.py` → `_get_stale_snapshot_fallback()`

**المشكلة الحالية:** يستخدم `redis.keys(pattern)` وهو أمر O(N) خطير على Redis في الإنتاج.

**الإصلاح:** استبدال `keys()` بمفتاح ثابت لآخر snapshot ناجح:

```python
# بدلاً من SCAN/KEYS:
STALE_KEY = f"display:school_snapshot:stale:school:{school_id}:day:{day_str}"
```

**كود مقترح:**
```python
def _save_stale_fallback(school_id: int, snap: dict) -> None:
    """حفظ نسخة احتياطية عند كل build ناجح."""
    day_str = str(timezone.localdate())
    key = f"display:school_snapshot:stale:school:{int(school_id)}:day:{day_str}"
    try:
        cache.set(key, snap, timeout=6 * 60 * 60)  # 6 ساعات
    except Exception:
        pass

def _get_stale_snapshot_fallback(school_id: int) -> dict | None:
    """استرجاع آخر snapshot احتياطي بدون KEYS."""
    day_str = str(timezone.localdate())
    key = f"display:school_snapshot:stale:school:{int(school_id)}:day:{day_str}"
    try:
        snap = cache.get(key)
        if isinstance(snap, dict):
            if "meta" not in snap:
                snap["meta"] = {}
            snap["meta"]["is_stale"] = True
            return snap
    except Exception:
        pass
    return None
```

### 1.5 تقليل Redis Connection Pool Overhead

**الملف:** `render.yaml`

```
REDIS_MAX_CONNECTIONS=30              # كان 20 (لـ 2 workers كافي)
```

> **ملاحظة:** لا ترفعها أكثر من 50 على Redis Starter (25MB).

---

## المرحلة 2: CDN + Edge Caching (تكلفة = $0)

> **الهدف:** Cloudflare يخدم ~80% من snapshot requests بدون وصول للسيرفر  
> **الشاشات:** 2,000 → 5,000  
> **المدة:** 2-3 ساعات

### 2.1 إنشاء Cloudflare Cache Rule

**الموقع:** Cloudflare Dashboard → Rules → Cache Rules

```
Rule Name: Display Snapshot Edge Cache
When: URI Path starts with "/api/display/snapshot/"
Then:
  - Cache eligibility: Eligible for cache
  - Edge TTL: Override origin → 15 seconds
  - Browser TTL: Override origin → 0 seconds (bypass)
  - Cache Key: Include query string: IGNORE (مهم جداً!)
  - Respect Origin: Strong ETags
```

**لماذا هذا مهم؟** 
- 100 شاشة من نفس المدرسة تطلب نفس الـ snapshot → Cloudflare يخدم 99 منها من الـ Edge
- حتى 15 ثانية edge cache تقلل الحمل على السيرفر بـ 75-90%

### 2.2 تحسين Headers من السيرفر

الكود الحالي في `snapshot()` يُرسل:
```
Cache-Control: public, max-age=0, must-revalidate, s-maxage={edge_ttl}
```

هذا صحيح. `s-maxage` يتحكم في Cloudflare Edge، و `max-age=0, must-revalidate` يمنع كاش المتصفح.

**تحسين مقترح:** رفع `DISPLAY_SNAPSHOT_EDGE_MAX_AGE`:

```
DISPLAY_SNAPSHOT_EDGE_MAX_AGE=15      # كان 10
```

### 2.3 إضافة Cloudflare Transform Rule لحذف Cookie

**الموقع:** Cloudflare Dashboard → Rules → Transform Rules → Modify Request Header

```
Rule Name: Strip Cookies from Display API
When: URI Path starts with "/api/display/"
Then:
  - Remove header: Cookie
```

**لماذا؟** SnapshotEdgeCacheMiddleware يحذف Set-Cookie من الاستجابة، لكن إرسال Cookie في الطلب قد يجعل Cloudflare يتجاهل الكاش.

### 2.4 حساب التأثير

| بدون Edge Cache | مع Edge Cache (15s) |
|----------------|---------------------|
| 5,000 req/20sec = 250 req/sec على السيرفر | ~25-50 req/sec على السيرفر |
| كل request يمر عبر Django | 80-90% من Cloudflare Edge |
| 2 workers مُحمّلة بالكامل | 2 workers فيها حمل خفيف |

---

## المرحلة 3: إدارة WebSocket + اتصالات (تكلفة ~$7/شهر)

> **الهدف:** WebSocket يخدم 10,000 شاشة بتحديثات فورية  
> **الشاشات:** 5,000 → 10,000  
> **المدة:** يوم واحد

### 3.1 ترقية Redis إلى Starter Plus

**الموقع:** Render Dashboard

```
Redis Plan: Starter Plus ($7/month)
Memory: 100MB (بدلاً من 25MB)
Connections: 100 (بدلاً من 20)
```

**لماذا؟**
- كل WS connection ≈ 50-100KB Redis memory (channel groups + message buffer)
- 25MB Redis = ~250-500 connections فقط
- 100MB Redis = ~1,000-2,000 connections

### 3.2 WebSocket Connection Limit المتدرج

**الملف:** `render.yaml`

```
WS_MAX_CONNECTIONS=3000               # كان 2000
WS_CHANNEL_CAPACITY=3000             # كان 2000
```

### 3.3 تحسين Polling Fallback للشاشات بدون WS

**الملف:** `render.yaml`

```
# شاشات بدون WS ترجع للـ polling كل 30 ثانية بدلاً من 20
REFRESH_EVERY=30
```

**لماذا؟** مع Edge Cache 15 ثانية، polling كل 30 ثانية يعني الشاشة تحصل على بيانات عمرها 15-30 ثانية، وهذا مقبول لأن dayEngine يتعامل مع التوقيت محلياً.

### 3.4 Graceful Degradation عند الحمل العالي

**تحسين مقترح في** `display/consumers.py`:

```python
async def connect(self):
    # إذا وصلنا للحد الأقصى، أرسل رسالة ودية وارفض الاتصال
    from display.ws_metrics import ws_metrics
    active = ws_metrics.connections_active
    max_conns = int(getattr(settings, 'WS_MAX_CONNECTIONS_PER_INSTANCE', 2000))
    
    if active >= max_conns:
        await self.close(code=4503)  # Service Unavailable
        return
    
    # ... باقي الكود الحالي
```

العميل (display.js) سيتراجع تلقائياً للـ polling عند رفض WS.

---

## المرحلة 4: بنية تحتية + Auto-scaling (تكلفة ~$50-150/شهر)

> **الهدف:** 30,000 شاشة متزامنة  
> **الشاشات:** 10,000 → 30,000  
> **المدة:** أسبوع

### 4.1 ترقية خطة Render

```
Web Plan: Standard ($25/month)
  - 1 GB RAM (بدلاً من 512MB)
  - More CPU
  
Redis Plan: Standard ($30/month) 
  - 256MB Memory
  - 256 Connections
  - Persistence enabled
```

### 4.2 رفع Workers

**الملف:** `render.yaml`

```
WEB_CONCURRENCY=8                     # كان 2
```

**حساب Workers المطلوب:**
- 30,000 شاشة × 1% cache miss = 300 rebuild/دورة
- كل rebuild = 300ms → 300 × 0.3s = 90 ثانية عمل
- 8 workers → 90/8 = ~11 ثانية (مقبول)
- مع Edge Cache: 80% يُخدم من CDN → 60 rebuild/دورة → 60 × 0.3 / 8 = ~2.25 ثانية (ممتاز)

### 4.3 Database Connection Pooling

**الملف:** `render.yaml` (إضافة PgBouncer أو استخدام Django persistent connections)

```
CONN_MAX_AGE=600                      # موجود حالياً (جيد)
```

**إضافة خيارات:**
```
DB_CONN_HEALTH_CHECKS=True            # Django 5.1 built-in
```

**الملف:** `config/settings.py` (إضافة)

```python
# Database connection health check (Django 5.1+)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = env_bool("DB_CONN_HEALTH_CHECKS", "True")
```

### 4.4 Horizontal Scaling (اختياري)

إذا لم يكفِ سيرفر واحد:

**خيار A: Render Auto-scaling**
```yaml
# render.yaml
scaling:
  minInstances: 2
  maxInstances: 5
  targetCPUPercent: 70
```

**خيار B: WS على سيرفر مخصص**
- فصل WebSocket عن HTTP بخدمتين مستقلتين
- WS service: Daphne مع Redis Channel Layer
- HTTP service: Gunicorn + CDN caching

### 4.5 Redis Sharding (>20,000 شاشة)

عند تجاوز 20,000 شاشة، يمكن فصل Redis لغرضين:

```
REDIS_URL=redis://cache-redis        # للكاش (django-redis)
REDIS_CHANNEL_URL=redis://ws-redis   # لـ Channel Layer (WebSocket)
```

**الملف:** `config/settings.py` (تعديل CHANNEL_LAYERS)

```python
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.getenv("REDIS_CHANNEL_URL", REDIS_URL)],
            # ...
        },
    },
}
```

---

## خطة التنفيذ المرحلية

### الأسبوع 1 (المرحلة 1 + 2)

| اليوم | المهمة | الملف |
|------|--------|------|
| **1** | رفع TTL + تفعيل V2 | `render.yaml` (env vars) |
| **1** | إصلاح `_get_stale_snapshot_fallback()` | `schedule/api_views.py` |
| **2** | إنشاء Cloudflare Cache Rule | Cloudflare Dashboard |
| **2** | إنشاء Transform Rule | Cloudflare Dashboard |
| **2** | رفع Edge Max-Age | `render.yaml` |

### الأسبوع 2 (المرحلة 3)

| اليوم | المهمة | الملف |
|------|--------|------|
| **1** | ترقية Redis | Render Dashboard |
| **1** | رفع WS limits | `render.yaml` |
| **2** | إضافة Graceful Degradation | `display/consumers.py` |

### الأسبوع 4+ (المرحلة 4 - حسب الحاجة)

| اليوم | المهمة | الملف |
|------|--------|------|
| **1** | ترقية Web plan | Render Dashboard |
| **1** | رفع Workers إلى 8 | `render.yaml` |
| **2** | DB health checks | `config/settings.py` |
| **3** | اختبار حمل + تعديل | Load testing |

---

## مراقبة الأداء

### مقاييس يجب مراقبتها

```
GET /api/display/metrics/?probe=true
```

| المقياس | الهدف | إنذار |
|---------|------|------|
| `token_hit / (token_hit + token_miss)` | > 90% | < 70% |
| `school_hit / (school_hit + school_miss)` | > 95% | < 80% |
| `build_avg_ms` | < 500ms | > 1000ms |
| `build_count` (per interval) | < 50 | > 200 |

### WS Metrics

```
GET /api/display/ws-metrics/
```

| المقياس | الهدف | إنذار |
|---------|------|------|
| `connections_active` | < WS_MAX_CONNECTIONS × 80% | > 90% |
| `broadcast_latency_avg_ms` | < 10ms | > 100ms |
| `health` | "ok" | "critical" |

---

## حاسبة السعة

```
الشاشات المتزامنة = min(
    Workers × 1000 / poll_rate,              # CPU capacity
    Redis_MB × 10,                            # Redis memory
    WS_MAX_CONNECTIONS × instances,           # WS limit
    Edge_cache_hit_rate × CDN_capacity        # CDN offload
)
```

### أمثلة:

| الوضع | Workers | Redis | WS Max | Edge | ≈ الحد الأقصى |
|------|---------|-------|--------|------|--------------|
| **الحالي** | 2 | 25MB | 2,000 | 0% | ~500-1,000 |
| **بعد مرحلة 1+2** | 2 | 25MB | 2,000 | 80% | ~2,000-5,000 |
| **بعد مرحلة 3** | 2 | 100MB | 3,000 | 80% | ~5,000-10,000 |
| **بعد مرحلة 4** | 8 | 256MB | 5,000 | 85% | ~15,000-30,000 |

---

## تنبيهات مهمة

1. **لا تنتقل لمرحلة قبل إكمال سابقتها** — كل مرحلة تبني على التحسينات السابقة
2. **المرحلة 1 هي الأهم** — تحسينات بدون تكلفة ترفع الأداء 2-4x
3. **Cloudflare Cache (مرحلة 2)** هي game-changer — تقلل حمل السيرفر 80-90%
4. **اختبر كل مرحلة** عبر `/api/display/metrics/` و `/api/display/ws-metrics/` قبل الانتقال للتالية
5. **`redis.keys()` في الكود الحالي** يجب إصلاحه فوراً (مرحلة 1.4) — خطر أداء حقيقي
