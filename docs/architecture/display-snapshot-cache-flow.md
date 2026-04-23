# Display Snapshot Cache Flow

آخر تحديث: 2026-04-23

هذه الملاحظة تخص **الدفعة 3 فقط**: تحسين `snapshot/cache flow` داخليًا بدون تغيير topology التشغيلية أو routes أو API contracts.

## ما الذي بقي كما هو

- مفتاح steady cache الحالي ما زال `snapshot:v9:school:<school_id>:day:<day>`.
- اسم المفتاح ما زال revision-agnostic لتجنب كسر التوافق الحالي.
- `display_snapshot_worker` بقي embedded كما هو.

## ما الذي تحسن داخليًا

### 1. توحيد صلاحية cache entries

تمت إضافة طبقة تحقق موحدة قبل اعتماد أي snapshot cache entry، بحيث يمكن رفض entry إذا:

- كانت تحمل `schedule_revision` أقدم من revision المطلوب.
- كانت snapshot من نوع `before_hours` لكن `next_wake_at` مر بالفعل.

هذا منع بعض hit الزائف من المسارات السريعة التي كانت تقرأ الكاش مباشرة بدون نفس قواعد `get_or_build_snapshot()`.

### 2. تقليل rebuild عند lock contention

عند وجود build قيد التنفيذ لنفس المدرسة/اليوم، صار المسار ينتظر قليلًا لالتقاط steady cache الناتج قبل السقوط إلى `BYPASS`.  
هذا يقلل duplicate rebuild خصوصًا تحت الضغط المتزامن.

### 3. تحسين queue/build coordination

قبل enqueue جديد، يتم الآن فحص ما إذا كانت steady cache تحتوي بالفعل snapshot صالحة لأحدث revision المطلوب.  
إذا كانت موجودة، يتم تخطي enqueue بسبب `already_cached`.

### 4. تقليل query إضافي غير ضروري

عند وجود `period_classes_map` جاهزة لنفس اليوم، لم يعد المسار يبني query ثانية لـ `period_classes` إذا كان الـ period الحالي غير موجود داخل الخريطة.

### 5. metrics أوضح

أضيفت counters جديدة تساعد في التشخيص:

- `metrics:snapshot_cache:revision_reject`
- `metrics:snapshot_cache:wake_boundary_reject`

هذه counters توضح متى تم تجاهل cache entry لأنها قديمة revision-wise أو لأنها تجاوزت wake boundary.
