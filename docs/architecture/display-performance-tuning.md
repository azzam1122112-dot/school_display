# Display Performance Tuning

آخر تحديث: 2026-04-23

هذه الدفعة تضيف تحسينات صغيرة وآمنة فوق طبقة `observability` بدون تغيير topology أو routes أو API أو سلوك الشاشة.

## ما الذي تم تحسينه

### 1. تقليل ضوضاء logging

- تم إضافة sampling deterministic داخل `schedule.snapshot_observability`
- metrics تبقى كاملة كما هي
- logs عالية التكرار مثل:
  - `snapshot_cache hit`
  - `snapshot_build start`
  - `snapshot_queue queued/dequeued`
  أصبحت sampled بدل أن تُكتب لكل طلب
- الأحداث الأهم تبقى مرئية دائمًا أو شبه دائمًا:
  - `older_revision`
  - `past_wake_boundary`
  - `worker_unavailable`
  - queue wait البطيء
  - build البطيء

### 2. تقليل تكرار الحسابات داخل build path

داخل `_build_final_snapshot`:

- تم توحيد استخراج `weekday` في helper واحد
- تم تجميع رسائل الشاشة الافتراضية في helper واحد بدل نداءات متكررة متفرقة
- تم إضافة cache محلي داخل build لاستدعاءات `_infer_period_index`
- تم إعادة استخدام `period_classes_map` المحلي داخل نفس build بدل إعادة استنتاج نفس البيانات أكثر من مرة

### 3. تحسين queue coordination

- job payload أصبح يحمل `latest_rev` المعروف وقت enqueue بدل `requested rev` فقط
- هذا يقلل فرص أن يدخل worker في coalescing إضافي غير ضروري بعد dequeue
- النتيجة المتوقعة: تقليل outdated/coalesced work عندما تصل revisions متقاربة بسرعة

### 4. safeguards أوضح للبناء

- تمت إضافة soft timeout budget للبناء:
  - `DISPLAY_SNAPSHOT_BUILD_SOFT_TIMEOUT_MS`
- عند تجاوز budget:
  - لا يتغير السلوك الخارجي
  - لكن يسجل النظام الحدث ويزيد counter داخلي
- هذا يسمح بالتشخيص المبكر قبل أن تتحول builds البطيئة إلى مشكلة تشغيلية

## counters / logs الجديدة ذات الصلة

- `metrics:snapshot_build:soft_timeout`
- log event:
  - `event=snapshot_build_budget`

## الإعدادات الجديدة

- `DISPLAY_SNAPSHOT_CACHE_HIT_LOG_SAMPLE_EVERY`
- `DISPLAY_SNAPSHOT_CACHE_MISS_LOG_SAMPLE_EVERY`
- `DISPLAY_SNAPSHOT_BUILD_START_LOG_SAMPLE_EVERY`
- `DISPLAY_SNAPSHOT_BUILD_END_LOG_SAMPLE_EVERY`
- `DISPLAY_SNAPSHOT_QUEUE_LOG_SAMPLE_EVERY`
- `DISPLAY_SNAPSHOT_BUILD_SLOW_LOG_MS`
- `DISPLAY_SNAPSHOT_QUEUE_SLOW_WAIT_LOG_MS`
- `DISPLAY_SNAPSHOT_BUILD_SOFT_TIMEOUT_MS`

كلها اختيارية، والافتراضات الحالية محافظة وموجهة لتقليل الضوضاء لا لتغيير السلوك.

## الأثر المتوقع

- حمل أقل من logging على المسار الساخن
- وضوح أفضل عند وجود مشاكل فعلية بدل flood من logs الطبيعية
- تقليل بسيط في كلفة build الداخلية
- تقليل بسيط في churn الخاص بالـ queue عند تغيّر revision بسرعة

## ما لم يتغير

- لا يوجد فصل worker
- لا يوجد تغيير في topology
- لا يوجد تغيير في routes أو API contracts
- لا يوجد تغيير مقصود في payload أو منطق الشاشة
