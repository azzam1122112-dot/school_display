# حل مشكلة Cold Start عند بداية الدوام

## ✅ التعديلات المطبقة

### 1. إزالة التاريخ من Cache Key

**الملف:** `schedule/api_views.py`

```python
# قبل التعديل ❌
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady:{str(timezone.localdate())}"
    # المشكلة: عند 00:00 يتغير التاريخ → cache miss لجميع المدارس

# بعد التعديل ✅
def _steady_cache_key_for_school_rev(school_id: int, rev: int) -> str:
    return f"snapshot:v5:school:{int(school_id)}:rev:{int(rev)}:steady"
    # الحل: الـ revision كافٍ - يزيد عند أي تعديل
```

---

## 🔄 الآلية الجديدة

### قبل الإصلاح:
```
23:59 → Cache Key: snapshot:v5:school:123:rev:5:steady:2026-02-01 ✅
00:00 → Cache Key: snapshot:v5:school:123:rev:5:steady:2026-02-02 ❌ (مفتاح جديد!)
       ↓
     Cache Miss → Cold Start لجميع المدارس!
```

### بعد الإصلاح:
```
23:59 → Cache Key: snapshot:v5:school:123:rev:5:steady ✅
00:00 → Cache Key: snapshot:v5:school:123:rev:5:steady ✅ (نفس المفتاح!)
       ↓
     Cache Hit → البيانات متوفرة فوراً!
```

---

## ⚠️ نقطة مهمة: متى يتجدد الكاش؟

الـ `schedule_revision` يزيد تلقائياً عند:

1. ✅ **تعديل الجدول الدراسي** (Period, Break, DaySchedule)
2. ✅ **تعديل الإعدادات** (SchoolSettings)
3. ✅ **إضافة/تعديل إعلان** (Announcement)
4. ✅ **إضافة/تعديل انتظار** (StandbyAssignment)
5. ✅ **إضافة/تعديل مناوبة** (DutyAssignment)

**لكن:** الـ revision **لا يزيد تلقائياً** عند بداية يوم جديد إذا لم يكن هناك تعديل!

---

## 🎯 التوصية: إضافة Cron Job (اختياري)

إذا كنت تريد **ضمان** تجديد الكاش كل يوم حتى بدون تعديلات:

### الطريقة 1: Django Management Command

```python
# schedule/management/commands/bump_daily_revision.py
from django.core.management.base import BaseCommand
from core.models import School
from schedule.cache_utils import bump_schedule_revision_for_school_id_debounced

class Command(BaseCommand):
    help = 'Bump schedule revision for all active schools (daily)'

    def handle(self, *args, **options):
        schools = School.objects.filter(is_active=True)
        count = 0
        
        for school in schools:
            try:
                bumped = bump_schedule_revision_for_school_id_debounced(
                    school_id=school.id,
                    force=True  # تجاوز الـ debounce
                )
                if bumped:
                    count += 1
                    self.stdout.write(f"✅ Bumped revision for school {school.id}")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"❌ Failed for school {school.id}: {e}")
                )
        
        self.stdout.write(
            self.style.SUCCESS(f"Done! Bumped {count} schools")
        )
```

**تشغيل يدوي:**
```bash
python manage.py bump_daily_revision
```

**تشغيل تلقائي عبر Cron (على السيرفر):**
```bash
# crontab -e
0 0 * * * cd /path/to/project && python manage.py bump_daily_revision >> /var/log/bump_revision.log 2>&1
```

---

### الطريقة 2: Render Cron Job (الأسهل)

إذا كنت تستخدم Render.com:

1. اذهب إلى Dashboard → Cron Jobs
2. أضف cron job جديد:
   - **Command:** `python manage.py bump_daily_revision`
   - **Schedule:** `0 0 * * *` (كل يوم منتصف الليل)
   - **Environment:** نفس بيئة الـ web service

---

### الطريقة 3: Celery Beat (الأفضل للمشاريع الكبيرة)

```python
# config/celery.py (أو أي ملف celery config)

from celery import Celery
from celery.schedules import crontab

app = Celery('school_display')

app.conf.beat_schedule = {
    'bump-daily-revision': {
        'task': 'schedule.tasks.bump_daily_revision',
        'schedule': crontab(hour=0, minute=0),  # كل يوم 00:00
    },
}

# schedule/tasks.py
from celery import shared_task
from core.models import School
from schedule.cache_utils import bump_schedule_revision_for_school_id_debounced

@shared_task
def bump_daily_revision():
    schools = School.objects.filter(is_active=True)
    for school in schools:
        try:
            bump_schedule_revision_for_school_id_debounced(
                school_id=school.id,
                force=True
            )
        except Exception as e:
            # Log error but continue
            pass
```

---

## 📊 التحقق من نجاح الإصلاح

### 1. مراقبة اللوجز عند 00:00

```bash
# يجب أن ترى:
✅ "cache hit" بدلاً من "cache miss"
✅ "steady_hit" بدلاً من "steady_miss"
❌ لا يجب أن ترى "snapshot build" عند 00:00 لجميع المدارس
```

### 2. استخدام Metrics Endpoint

```bash
curl -H "X-Display-Metrics-Key: YOUR_KEY" \
  https://school-display.com/api/display/metrics/

# تحقق من:
{
  "metrics:snapshot_cache:steady_hit": 450,   ✅ عالي
  "metrics:snapshot_cache:steady_miss": 2,    ✅ قليل
  "metrics:snapshot_cache:build_count": 3,    ✅ قليل
}
```

### 3. اختبار يدوي

```python
# في Django shell
from django.core.cache import cache
from schedule.api_views import _steady_cache_key_for_school_rev

# افحص إذا الكاش موجود
school_id = 123  # استبدل برقم مدرسة حقيقي
rev = 5          # استبدل برقم الـ revision الحالي

key = _steady_cache_key_for_school_rev(school_id, rev)
print(f"Cache key: {key}")
print(f"Cache exists: {cache.get(key) is not None}")
```

---

## 🎯 الخلاصة

### ✅ ما تم إصلاحه:
1. إزالة التاريخ من cache key
2. الاعتماد على `schedule_revision` فقط
3. منع cold start عند 00:00

### ⚠️ ما يحتاج متابعة (اختياري):
1. إضافة cron job لضمان تجديد يومي
2. مراقبة الـ metrics
3. إضافة pre-warming للكاش

### 📅 الجدول الزمني:
- ✅ **اليوم**: الإصلاح الفوري مطبق
- 🔄 **الأسبوع القادم**: مراقبة الأداء
- 📊 **الشهر القادم**: إضافة metrics dashboard

---

**التاريخ:** 2 فبراير 2026  
**الحالة:** ✅ **جاهز للاختبار**
