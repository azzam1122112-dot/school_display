# 🚨 تقرير: تحليل مشكلة Cold Start عند بداية الدوام

## 📋 **الملخص التنفيذي**

**المشكلة:** جميع المدارس عانت من عدم عرض البيانات عند بداية الدوام صباحاً (Cold Start Issue)

**السبب الجذري:** عند منتصف الليل (00:00)، يتغير `timezone.localdate()` من `2026-02-01` إلى `2026-02-02`، مما يجعل **جميع cache keys غير صالحة فوراً**.

---

## 🔍 **التحليل التفصيلي**

### 1. **مفتاح الـ Cache يتضمن التاريخ:**

```python
# schedule/api_views.py:67
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady:{str(timezone.localdate())}"
    #                                                                   ^^^^^^^^^^^^^^^^^^^^^^^^
    #                                                                   المشكلة هنا!
```

**النتيجة:**
- عند 23:59: `snapshot:v5:school:123:rev:5:steady:2026-02-01` ✅
- عند 00:00: `snapshot:v5:school:123:rev:5:steady:2026-02-02` ❌ (مفتاح جديد!)
- **الكاش القديم لا يزال موجود لكن لا يُستخدم!**

---

### 2. **Thundering Herd عند بداية اليوم:**

```
00:00 - جميع الشاشات (200+) تطلب في نفس اللحظة
      ↓
Cache Miss لجميع المدارس
      ↓
جميع السيرفرات تبني الـ snapshots في نفس الوقت
      ↓
ضغط عالي جداً على:
  - Database (الجداول الدراسية)
  - Redis (بناء الكاش الجديد)
  - CPU (build_day_snapshot)
      ↓
بطء شديد أو timeout
      ↓
❌ الشاشات لا تعرض البيانات
```

---

### 3. **اللوجز تؤكد المشكلة:**

من اللوجز السابقة:
```log
[02/Feb/2026:00:02:00] nocache=1&_t=1769979718843  ⚠️ Force refresh
[02/Feb/2026:00:04:59] nocache=1&_t=1769979897975  ⚠️ Multiple refreshes
[02/Feb/2026:00:05:00] nocache=1&_t=1769979899117  ⚠️ في نفس الثانية
```

**التفسير:**
1. عند 00:00 تتغير الساعة → تحديث الحصة
2. جميع الشاشات تطلب `nocache=1` (countdown zero)
3. Cache miss لأن التاريخ تغير
4. البناء يأخذ وقت طويل
5. الشاشات تحاول مرة أخرى (retry)

---

## ✅ **الحلول المقترحة**

### **الحل 1: إزالة التاريخ من مفتاح الـ Cache (الأفضل)**

**المشكلة:** الكود الحالي يُخزن cache منفصل لكل يوم لمنع عرض بيانات يوم أمس.

**الحل:** الاعتماد على `schedule_revision` بدلاً من التاريخ:

```python
# Before (المشكل)
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady:{str(timezone.localdate())}"

# After (الحل)
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    # لا نضيف التاريخ - الـ revision كافٍ للتمييز
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady"
```

**المزايا:**
- ✅ لا cold start عند 00:00
- ✅ الكاش يبقى صالح عبر الأيام
- ✅ عند تغيير الجدول، يزيد الـ revision تلقائياً

**التحدي:**
- ⚠️ يجب التأكد أن الـ revision يزيد عند منتصف الليل إذا تغير اليوم الدراسي

---

### **الحل 2: Pre-warming الكاش قبل 00:00 (تكميلي)**

```python
# في cron job أو celery task
# كل يوم الساعة 23:50
@task
def prewarm_display_cache():
    """تجهيز الكاش لليوم الجديد قبل بداية الدوام"""
    
    tomorrow_key = (timezone.localdate() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # جلب جميع المدارس النشطة
    schools = School.objects.filter(is_active=True)
    
    for school in schools:
        try:
            settings = school.schedule_settings
            # بناء الـ snapshot لليوم التالي مسبقاً
            snap = build_day_snapshot(settings)
            
            # حفظه في الكاش بمفتاح الغد
            cache.set(
                f"snapshot:v5:school:{school.id}:rev:{rev}:steady:{tomorrow_key}",
                snap,
                timeout=3600  # ساعة واحدة
            )
            logger.info(f"Pre-warmed cache for school {school.id}")
        except Exception as e:
            logger.error(f"Failed to pre-warm school {school.id}: {e}")
```

**التنفيذ:**
```python
# في settings.py
CELERY_BEAT_SCHEDULE = {
    'prewarm-display-cache': {
        'task': 'display.tasks.prewarm_display_cache',
        'schedule': crontab(hour=23, minute=50),  # كل يوم 23:50
    },
}
```

---

### **الحل 3: Staggered Cache Invalidation (توزيع)**

بدلاً من تغيير الكاش للجميع عند 00:00، نوزع التغيير:

```python
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    # استخدام hash لتوزيع التغيير على 24 ساعة
    hour_offset = hash(school_id) % 24
    adjusted_date = timezone.localtime() - timedelta(hours=hour_offset)
    date_key = adjusted_date.strftime("%Y-%m-%d")
    
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady:{date_key}"
```

**النتيجة:**
- School 1: cache يتجدد الساعة 00:00
- School 2: cache يتجدد الساعة 01:00
- School 3: cache يتجدد الساعة 02:00
- ...إلخ

**المشكلة:** قد يعرض بيانات يوم أمس لبعض الوقت ❌

---

### **الحل 4: Graceful Degradation (احتياطي)**

عند cache miss، نعرض بيانات يوم أمس مؤقتاً بينما نبني الجديد:

```python
def get_snapshot_with_fallback(school_id, rev, day_key):
    # محاولة 1: كاش اليوم
    snap = cache.get(f"snapshot:v5:school:{school_id}:rev:{rev}:steady:{day_key}")
    if snap:
        return snap
    
    # محاولة 2: كاش يوم أمس (stale but usable)
    yesterday = (timezone.localdate() - timedelta(days=1)).strftime("%Y-%m-%d")
    stale_snap = cache.get(f"snapshot:v5:school:{school_id}:rev:{rev}:steady:{yesterday}")
    
    if stale_snap:
        # نعرض بيانات يوم أمس مؤقتاً
        stale_snap['meta']['is_stale'] = True
        stale_snap['meta']['stale_date'] = yesterday
        
        # نبني الجديد في الخلفية (async)
        if not cache.get(f"building:{school_id}:{day_key}"):
            cache.set(f"building:{school_id}:{day_key}", "1", timeout=60)
            build_snapshot_async.delay(school_id, rev, day_key)
        
        return stale_snap
    
    # محاولة 3: بناء جديد (blocking)
    return build_snapshot(school_id, rev, day_key)
```

---

## 🎯 **الحل الموصى به (Multi-layered)**

### **الطبقة 1: إصلاح فوري (اليوم)**

```python
# schedule/api_views.py

def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    # إزالة التاريخ - الاعتماد على revision فقط
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady"

# إضافة: زيادة revision عند منتصف الليل
def bump_revision_on_new_day():
    """يُنفذ عند 00:00 لزيادة revision لجميع المدارس"""
    # هذا يضمن أن الكاش القديم لن يُستخدم
    schools = School.objects.filter(is_active=True)
    for school in schools:
        try:
            rev = get_cached_schedule_revision_for_school_id(school.id)
            set_cached_schedule_revision_for_school_id(school.id, rev + 1)
        except Exception as e:
            logger.error(f"Failed to bump revision for school {school.id}: {e}")
```

**Cron Job:**
```python
CELERY_BEAT_SCHEDULE = {
    'bump-revision-new-day': {
        'task': 'display.tasks.bump_revision_on_new_day',
        'schedule': crontab(hour=0, minute=0),  # كل يوم 00:00
    },
}
```

---

### **الطبقة 2: Pre-warming (أسبوع واحد)**

```python
# تجهيز الكاش قبل 00:00 بـ 10 دقائق
CELERY_BEAT_SCHEDULE = {
    'prewarm-display-cache': {
        'task': 'display.tasks.prewarm_display_cache',
        'schedule': crontab(hour=23, minute=50),
    },
}
```

---

### **الطبقة 3: Graceful Degradation (شهر واحد)**

```python
# إضافة fallback logic في get_snapshot
def get_snapshot_with_fallback(school_id, rev, day_key):
    # ...الكود أعلاه...
    pass
```

---

## 📊 **التأثير المتوقع**

### **قبل الإصلاح:**
```
00:00 - جميع المدارس: Cache Miss
      ↓
      Cold Start لـ 200+ مدرسة
      ↓
      تحميل عالي على DB/Redis
      ↓
      ❌ فشل عرض البيانات لمدة 5-10 دقائق
```

### **بعد الإصلاح:**
```
23:50 - Pre-warming (تجهيز الكاش مسبقاً)
      ↓
00:00 - Revision Bump (زيادة الرقم فقط - سريع)
      ↓
00:00+ - الشاشات تطلب الكاش الجديد
      ↓
      ✅ الكاش جاهز مسبقاً
      ↓
      ✅ عرض فوري للبيانات
```

---

## 🚀 **خطة التنفيذ**

### **المرحلة 1: إصلاح فوري (اليوم)**
- [x] إزالة التاريخ من cache key
- [x] إضافة revision bump عند 00:00
- [x] اختبار على مدرسة واحدة

### **المرحلة 2: Pre-warming (الأسبوع القادم)**
- [ ] تطوير celery task للـ pre-warming
- [ ] اختبار في staging
- [ ] نشر في production

### **المرحلة 3: Monitoring (شهر واحد)**
- [ ] إضافة metrics للـ cache hit/miss
- [ ] Dashboard لمراقبة الأداء
- [ ] Alerting عند cold start

---

## 📈 **المقاييس للمراقبة**

```python
# Metrics to track:
- cache_hit_rate_at_00:00
- snapshot_build_time_avg
- snapshot_build_time_p95
- cold_start_duration
- schools_affected_count
- error_rate_at_00:00
```

---

**التاريخ:** 2 فبراير 2026  
**الأولوية:** 🔴 **عاجل - Critical**  
**التأثير:** 🎯 **جميع المدارس**
