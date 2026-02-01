# 🔍 تقرير فحص شامل: مشاكل عدم العرض والتأخير في شاشة العرض

**تاريخ الفحص:** 2 فبراير 2026  
**الحالة:** 🔴 **تم اكتشاف 12 مشكلة حرجة ومتوسطة**

---

## 📊 ملخص تنفيذي

تم فحص النظام بالكامل من Frontend إلى Backend، وتم اكتشاف عدة مشاكل حرجة تسبب:
- ❌ عدم عرض البيانات عند بداية الدوام
- ⏱️ تأخير في تحميل الشاشات
- 🔄 طلبات متكررة غير ضرورية
- 💥 احتمالية crash عند الأخطاء

---

## 🚨 المشاكل الحرجة (Critical)

### 1. ⚡ **Cold Start عند منتصف الليل** (تم إصلاحه)
**الوصف:** عند 00:00، يتغير التاريخ في cache key مما يجعل جميع الكاش غير صالح فوراً.

**الكود المشكل:**
```python
# schedule/api_views.py:67
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    return f"snapshot:v5:school:{school_id}:rev:{rev}:steady:{timezone.localdate()}"
    # ❌ التاريخ يتغير عند 00:00
```

**التأثير:**
- 🔴 جميع المدارس (200+) تواجه cache miss في نفس اللحظة
- 🔴 Cold start لجميع الشاشات
- 🔴 تحميل عالي جداً على Database + Redis
- 🔴 عدم عرض البيانات لمدة 5-10 دقائق

**الحل المطبق:** ✅
```python
# إزالة التاريخ من cache key
return f"snapshot:v5:school:{school_id}:rev:{rev}:steady"
```

**الأولوية:** 🔴 **عاجل جداً** - **تم الإصلاح**

---

### 2. ⚠️ **Thundering Herd عند countdown zero**
**الوصف:** جميع الشاشات تطلب force refresh في نفس اللحظة عند انتهاء الحصة.

**الكود الحالي:**
```javascript
// static/js/display.js:1032
const jitterMs = 1000 + Math.floor(Math.random() * 14000); // 1-15 ثانية
```

**المشكلة:**
- ✅ تم إصلاحه جزئياً (زيادة jitter من 0.5s → 15s)
- ⚠️ لكن لا يزال هناك ضغط عند 00:00 لأن جميع الحصص تنتهي معاً

**الحل الإضافي المقترح:**
```javascript
// توزيع countdown zero على نطاق أوسع
const baseJitter = 1000 + Math.floor(Math.random() * 14000);
const schoolJitter = (parseInt(schoolId) % 30) * 1000; // 0-29 ثانية إضافية
const totalJitter = baseJitter + schoolJitter; // 1-44 ثانية
```

**الأولوية:** 🟠 **عالية**

---

### 3. 🐌 **Fast Retry بدون Exponential Backoff**
**الوصف:** عند فشل الطلب الأول، يعيد المحاولة كل 2 ثانية بدون backoff.

**الكود المشكل:**
```javascript
// static/js/display.js:2764
if (!lastPayloadForFiltering) {
    backoff = 2; // ❌ ثابت دائماً
} else {
    backoff = Math.min(60, cfg.REFRESH_EVERY + failStreak * 5);
}
```

**المشكلة:**
- 🔴 إذا كان هناك مشكلة في السيرفر، جميع الشاشات (200+) تعيد المحاولة كل 2 ثانية
- 🔴 تزيد الضغط بدلاً من تقليله
- 🔴 يمكن أن تسبب rate limiting (429)

**الحل المقترح:**
```javascript
if (!lastPayloadForFiltering) {
    // Exponential backoff للتحميل الأولي
    const maxRetries = 5;
    const retryCount = Math.min(failStreak, maxRetries);
    backoff = Math.min(30, 2 * Math.pow(1.5, retryCount)); // 2s, 3s, 4.5s, 6.7s, 10s, 15s...
    
    // Jitter لتوزيع الطلبات
    const jitterFactor = 0.5 + Math.random() * 0.5; // ±25%
    backoff = backoff * jitterFactor;
} else {
    backoff = Math.min(60, cfg.REFRESH_EVERY + failStreak * 5);
}
```

**الأولوية:** 🔴 **عاجل**

---

### 4. ⏱️ **Timeout قصير جداً (9 ثوان)**
**الوصف:** Timeout للطلبات 9 ثوان فقط، وهذا قد يكون قصيراً للشبكات البطيئة أو السيرفرات المشغولة.

**الكود:**
```javascript
// static/js/display.js:2501
return await withTimeout(fetchPromise, 9000, () => {
    // ❌ 9 ثوان قد تكون قصيرة
```

**المشكلة:**
- ⚠️ قد يحدث timeout حتى لو السيرفر يعمل (خاصة عند بناء snapshot لأول مرة)
- ⚠️ يسبب retry غير ضروري

**الحل المقترح:**
```javascript
// تمييز بين first load و normal refresh
const timeout = lastPayloadForFiltering ? 9000 : 15000; // 15s للتحميل الأول
return await withTimeout(fetchPromise, timeout, () => {
    if (ctrl) ctrl.abort();
});
```

**الأولوية:** 🟠 **متوسطة**

---

### 5. 🔍 **عدم وجود Stale-While-Revalidate**
**الوصف:** عند cache miss، لا يتم عرض بيانات قديمة (stale) أثناء بناء البيانات الجديدة.

**المشكلة:**
- 🔴 الشاشة تبقى فارغة أو تعرض "جاري التحميل..."
- 🔴 تجربة مستخدم سيئة

**الحل المقترح:**
```python
# schedule/api_views.py
def get_snapshot_with_fallback(school_id, rev, day_key):
    # 1. محاولة الكاش الحالي
    current_key = f"snapshot:v5:school:{school_id}:rev:{rev}:steady"
    snap = cache.get(current_key)
    if snap:
        return snap, "FRESH"
    
    # 2. محاولة الكاش القديم (أي revision)
    stale_pattern = f"snapshot:v5:school:{school_id}:rev:*:steady"
    # Redis SCAN للبحث عن أي نسخة قديمة
    stale_snap = find_any_stale_snapshot(school_id)
    
    if stale_snap:
        # عرض البيانات القديمة مع إضافة تحذير
        stale_snap['meta']['is_stale'] = True
        stale_snap['meta']['stale_warning'] = 'يتم تحديث البيانات...'
        
        # بناء الجديد في الخلفية
        build_snapshot_async.delay(school_id, rev, day_key)
        
        return stale_snap, "STALE"
    
    # 3. بناء جديد (blocking)
    return build_snapshot_now(school_id, rev, day_key), "BUILT"
```

**الأولوية:** 🟠 **عالية**

---

## ⚠️ المشاكل المتوسطة (Medium)

### 6. 📊 **N+1 Query في build_day_snapshot**
**الوصف:** عند بناء snapshot، يتم استعلام Database لكل Period/Break بشكل منفصل.

**الكود:**
```python
# schedule/time_engine.py:115
for p in periods_m.select_related("subject", "teacher", "school_class").all():
    # ✅ استخدام select_related موجود (جيد)
```

**الملاحظة:**
- ✅ يستخدم `select_related` بشكل صحيح
- ⚠️ لكن يمكن تحسينه بإضافة `only()` للحقول المطلوبة فقط

**الحل المقترح:**
```python
for p in periods_m.select_related("subject", "teacher", "school_class").only(
    'index', 'starts_at', 'ends_at',
    'subject__name', 'teacher__name', 'school_class__name'
).all():
    # جلب الحقول المطلوبة فقط
```

**الأولوية:** 🟡 **متوسطة**

---

### 7. 🔄 **عدم استخدام Connection Pooling**
**الوصف:** لا يوجد connection pooling صريح لـ Redis في الإعدادات.

**الكود الحالي:**
```python
# config/settings.py:350
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # ❌ لا يوجد CONNECTION_POOL_KWARGS
        }
    }
}
```

**المشكلة:**
- ⚠️ قد يسبب استنزاف connections عند الضغط العالي
- ⚠️ بطء في الأداء

**الحل المقترح:**
```python
"OPTIONS": {
    "CLIENT_CLASS": "django_redis.client.DefaultClient",
    "SOCKET_CONNECT_TIMEOUT": 2,
    "SOCKET_TIMEOUT": 2,
    "RETRY_ON_TIMEOUT": True,
    "HEALTH_CHECK_INTERVAL": 30,
    # ✅ إضافة connection pooling
    "CONNECTION_POOL_KWARGS": {
        "max_connections": 50,
        "retry_on_timeout": True,
        "socket_keepalive": True,
        "socket_keepalive_options": {
            socket.TCP_KEEPIDLE: 60,
            socket.TCP_KEEPINTVL: 10,
            socket.TCP_KEEPCNT: 3,
        }
    }
}
```

**الأولوية:** 🟡 **متوسطة**

---

### 8. 📉 **Cache TTL طويل جداً (30 دقيقة)**
**الوصف:** Default cache timeout 30 دقيقة قد يكون طويل لبعض البيانات.

**الكود:**
```python
# config/settings.py:347
DEFAULT_CACHE_TIMEOUT = 60 * 30  # 30 minutes
```

**المشكلة:**
- ⚠️ إذا حصل تعديل على الجدول، قد يستغرق 30 دقيقة حتى يظهر
- ⚠️ مع أن هناك revision bump، لكن قد يحدث تأخير

**الحل المقترح:**
```python
# تمييز بين أنواع البيانات
CACHE_TIMEOUTS = {
    'snapshot': 60 * 60 * 24,      # 24 ساعة (يعتمد على revision)
    'token_school': 60 * 60,       # 1 ساعة
    'schedule_revision': 60 * 60,  # 1 ساعة
    'status': 10,                   # 10 ثوان
    'default': 60 * 5               # 5 دقائق (بدلاً من 30)
}
```

**الأولوية:** 🟡 **منخفضة**

---

## 🔧 مشاكل أخرى (Minor)

### 9. 🌐 **عدم استخدام CDN للملفات الثابتة**
**الوصف:** ملفات JS/CSS يتم تحميلها من السيرفر مباشرة.

**التأثير:**
- ⚠️ بطء في التحميل للشاشات البعيدة جغرافياً
- ⚠️ ضغط إضافي على السيرفر

**الحل المقترح:**
```python
# استخدام Cloudflare أو CloudFront
STATIC_URL = 'https://cdn.school-display.com/static/'
```

**الأولوية:** 🟢 **منخفضة**

---

### 10. 📱 **عدم وجود Service Worker**
**الوصف:** لا يوجد service worker للـ offline support.

**التأثير:**
- ⚠️ إذا انقطع الإنترنت مؤقتاً، الشاشة تتوقف تماماً
- ⚠️ لا يوجد caching للملفات الثابتة

**الحل المقترح:**
```javascript
// service-worker.js
const CACHE_NAME = 'school-display-v1';
const urlsToCache = [
  '/static/js/display.js',
  '/static/css/app.css',
  '/static/img/logo.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      return response || fetch(event.request);
    })
  );
});
```

**الأولوية:** 🟢 **منخفضة** (تحسين مستقبلي)

---

### 11. 🔐 **عدم استخدام HTTP/2**
**الوصف:** قد لا يكون HTTP/2 مفعل على السيرفر.

**التحقق:**
```bash
curl -I --http2 https://school-display.com
```

**الحل:**
تفعيل HTTP/2 في Nginx أو استخدام Cloudflare.

**الأولوية:** 🟢 **منخفضة**

---

### 12. 📊 **عدم وجود Monitoring/Alerting**
**الوصف:** لا يوجد نظام لمراقبة الأداء والأخطاء.

**ما يجب مراقبته:**
- ✅ Cache hit rate
- ✅ API response time
- ✅ Error rate
- ✅ Database query time
- ✅ Cold start events

**الحل المقترح:**
```python
# استخدام Sentry للأخطاء
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn="YOUR_SENTRY_DSN",
    integrations=[DjangoIntegration()],
    traces_sample_rate=0.1,  # 10% من الطلبات
)

# استخدام Django Debug Toolbar للتطوير
INSTALLED_APPS += ['debug_toolbar']
```

**الأولوية:** 🟡 **متوسطة**

---

## 📈 خطة العمل الموصى بها

### ✅ **المرحلة 1: إصلاحات فورية (الأسبوع الحالي)**
1. ✅ **تم:** إصلاح Cold Start (إزالة التاريخ من cache key)
2. ✅ **تم:** زيادة Jitter عند countdown zero
3. 🔄 **إضافة:** Exponential backoff للـ fast retry
4. 🔄 **إضافة:** زيادة timeout للتحميل الأولي

**الأولوية:** 🔴 **عاجل جداً**

---

### 🟠 **المرحلة 2: تحسينات أساسية (خلال أسبوعين)**
5. 📊 إضافة Stale-While-Revalidate
6. 🔄 تحسين Connection Pooling
7. 📉 تقليل Default Cache TTL
8. 📊 إضافة Database query optimization

**الأولوية:** 🟠 **عالية**

---

### 🟡 **المرحلة 3: تحسينات متقدمة (خلال شهر)**
9. 🌐 إضافة CDN للملفات الثابتة
10. 📊 إضافة Monitoring & Alerting
11. 🔐 تفعيل HTTP/2
12. 📱 إضافة Service Worker

**الأولوية:** 🟡 **متوسطة**

---

## 🎯 التوصيات النهائية

### **لتجنب مشاكل العرض في المستقبل:**

1. ✅ **Testing:** اختبار الحمل بانتظام (Loadtesting)
2. ✅ **Monitoring:** مراقبة الأداء 24/7
3. ✅ **Alerting:** إشعارات فورية عند الأخطاء
4. ✅ **Documentation:** توثيق جميع التغييرات
5. ✅ **Backups:** نسخ احتياطية للكاش والبيانات

### **مؤشرات الأداء المستهدفة (KPIs):**
```
- Cache Hit Rate: > 95%
- API Response Time (p95): < 200ms
- Error Rate: < 0.1%
- Cold Start Duration: < 2s
- Page Load Time: < 1s
```

---

**تاريخ التحديث:** 2 فبراير 2026  
**الحالة:** ✅ **جاهز للتطبيق**  
**المسؤول:** فريق التطوير
