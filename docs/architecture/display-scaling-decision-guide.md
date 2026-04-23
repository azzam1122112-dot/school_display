# Display Scaling Decision Guide

آخر تحديث: 2026-04-23

هذه الوثيقة تخص **الدفعة 6 فقط**: تحويل الـ observability الحالية إلى دليل تشغيل واتخاذ قرار للتوسع، بدون تغيير topology أو routes أو API contracts أو سلوك الشاشة.

## الهدف

- تحويل metrics الحالية إلى قراءة تشغيلية عملية.
- تحديد ما الذي يجب مراقبته في الإنتاج.
- اقتراح thresholds واضحة بدل الاعتماد على الانطباع العام.
- تحديد متى تكفي البنية الحالية، ومتى يصبح فصل worker أو زيادة الموارد قرارًا منطقيًا.

## مصدر البيانات الحالي

المصادر المعتمدة حاليًا:

- `/api/display/metrics/`
- `/api/display/ws-metrics/`
- structured logs من:
  - `event=snapshot_cache`
  - `event=snapshot_build`
  - `event=snapshot_queue`
  - `event=snapshot_metrics`
  - `event=snapshot_build_budget`
- worker liveness من:
  - `snapshot_worker_alive`
  - `snapshot_worker_age_sec`
  - `snapshot_queue_depth`
- wake/sleep behavior من:
  - `wake_boundary_reject`
  - `next_wake_at` داخل snapshot meta
  - `wake_broadcast_sent` / `wake_broadcast_failed`

## أهم metrics الحالية ومعناها

| المجموعة | metric | المعنى |
| --- | --- | --- |
| snapshot_cache | `hit` | عدد القرارات التي انتهت بخدمة snapshot صالح من cache |
| snapshot_cache | `miss` | عدد الحالات التي احتاجت rebuild أو queue أو stale fallback |
| snapshot_cache | `revision_reject` | cache entry موجودة لكن revision أقدم من المطلوب |
| snapshot_cache | `wake_boundary_reject` | snapshot `before_hours` تم رفضها بعد تجاوز `next_wake_at` |
| snapshot_build | `count` | عدد build completions المسجلة |
| snapshot_build | `source.inline.count` | builds حصلت داخل request path |
| snapshot_build | `source.queue.count` | builds حصلت داخل worker/materializer |
| snapshot_build | `source.stale.count` | مرات الرجوع إلى stale fallback |
| snapshot_build | `duration_ms_avg/max` | صورة عامة عن تكلفة البناء |
| snapshot_build | `soft_timeout` | مرات تجاوز budget التشغيلي للبناء |
| queue | `enqueue_count` | عدد الوظائف التي دخلت queue فعليًا |
| queue | `skipped_enqueue` | enqueue decisions التي لم تتحول إلى job جديدة |
| queue | `deduplicated_jobs` | وظائف تم dedupe لها بدل إضافة job جديدة |
| queue | `queue_wait_time_ms_avg/max` | الزمن بين enqueue وdequeue/serve |
| runtime | `snapshot_worker_alive` | هل worker يعتبر حيًا حسب heartbeat |
| runtime | `snapshot_queue_depth` | عدد العناصر المعلقة حاليًا في queue |

## كيف نقرأ Cache Health

### القراءة الأساسية

أهم 4 إشارات:

- `snapshot_cache.hit`
- `snapshot_cache.miss`
- `snapshot_cache.revision_reject`
- `snapshot_cache.wake_boundary_reject`

### تفسير عملي

- **hit مرتفع + miss منخفض**: cache صحية.
- **revision_reject منخفض لكن موجود**: طبيعي أثناء churn وتحديثات اليوم.
- **revision_reject مرتفع باستمرار**: queue/materialization لا تلحق تغيّرات revision.
- **wake_boundary_reject حول بداية اليوم**: طبيعي غالبًا، لأنه يعني أن cache القديمة لا تُخدم بعد وقت الاستيقاظ.
- **wake_boundary_reject منتشر طوال اليوم**: يحتاج مراجعة wake timing أو TTLs أو wake scheduler execution.

### thresholds مقترحة

#### hit ratio

احسب:

`hit_ratio = hit / (hit + miss)`

| الحالة | threshold |
| --- | --- |
| صحي | `>= 0.90` |
| يحتاج متابعة | `0.75 - 0.89` |
| غير مريح تشغيليًا | `< 0.75` |

#### miss ratio

احسب:

`miss_ratio = miss / (hit + miss)`

| الحالة | threshold |
| --- | --- |
| طبيعي | `<= 0.10` |
| مرتفع | `0.11 - 0.25` |
| مقلق | `> 0.25` |

#### revision reject

| الحالة | threshold |
| --- | --- |
| طبيعي | أقل من `5%` من إجمالي miss |
| يحتاج متابعة | `5% - 15%` من miss |
| مقلق | `> 15%` من miss |

## كيف نقرأ Queue Health

### القراءة الأساسية

راقب:

- `enqueue_count`
- `skipped_enqueue`
- `deduplicated_jobs`
- `queue_wait_time_ms_avg`
- `queue_wait_time_ms_max`
- `snapshot_queue_depth`
- `snapshot_worker_alive`
- `metrics:snapshot_queue:worker_unavailable`

### تفسير عملي

- **deduplicated_jobs و skipped_enqueue مرتفعان مع wait منخفض**: هذا جيد، يعني أن queue لا تستقبل churn زائد.
- **enqueue_count يرتفع مع queue_wait_avg يرتفع ومعه inline builds ترتفع**: worker لا يواكب الحمل.
- **queue_depth غير صفري لفترات طويلة**: علامة backlog.
- **worker_unavailable > 0**: مؤشر تشغيلي مهم حتى لو عاد worker لاحقًا.

### thresholds مقترحة

#### queue wait avg

| الحالة | threshold |
| --- | --- |
| صحي | `< 150ms` |
| يحتاج متابعة | `150ms - 400ms` |
| مقلق | `> 400ms` |

#### queue wait max

| الحالة | threshold |
| --- | --- |
| صحي | `< 1000ms` |
| يحتاج متابعة | `1000ms - 3000ms` |
| مقلق | `> 3000ms` |

#### queue depth

| الحالة | threshold |
| --- | --- |
| طبيعي | يتحرك قرب `0` أغلب الوقت |
| يحتاج متابعة | backlog صغير متكرر أثناء الذروة |
| مقلق | backlog مستمر عبر أكثر من دورة مراجعة |

#### worker unavailable signals

| الحالة | threshold |
| --- | --- |
| طبيعي | `0` |
| يحتاج متابعة | حدث متقطع أثناء deploy أو restart معروف |
| مقلق | أي تكرار مستمر خارج deploy window |

## كيف نقرأ Build Health

### القراءة الأساسية

راقب:

- `snapshot_build.count`
- `snapshot_build.duration_ms_avg`
- `snapshot_build.duration_ms_max`
- `snapshot_build.source.inline.count`
- `snapshot_build.source.queue.count`
- `snapshot_build.source.stale.count`
- `snapshot_build.soft_timeout`

### inline build ratio

احسب:

`inline_build_ratio = inline_count / (inline_count + queue_count + stale_count)`

هذه من أهم الإشارات التشغيلية، لأنها تبيّن هل web path يبني كثيرًا بدل أن يعتمد على cache/queue.

### thresholds مقترحة

| الحالة | threshold |
| --- | --- |
| صحي | `< 0.10` |
| يحتاج متابعة | `0.10 - 0.25` |
| مقلق | `> 0.25` |

### soft timeout count

| الحالة | threshold |
| --- | --- |
| طبيعي | `0` أو نادر جدًا |
| يحتاج متابعة | spikes قصيرة أثناء الذروة |
| مقلق | تكرار يومي أو نسبة `> 1%` من builds |

### duration interpretation

- **avg مرتفع فقط**: الحمل العام أكبر من المتوقع.
- **max مرتفع فقط**: هناك spikes أو مدرسة/حالة معينة ثقيلة.
- **soft_timeout مع inline مرتفع**: الخطر هنا على web responsiveness.
- **soft_timeout مع queue مرتفع لكن inline منخفض**: worker متعب، لكن web path ما زال محميًا نسبيًا.

## كيف نقرأ Wake/Sleep Behavior

لا توجد مجموعة metrics مستقلة كاملة للـ wake scheduler، لذلك القراءة الحالية تعتمد على 3 مصادر:

1. `wake_boundary_reject`
2. logs من `wake_broadcast_sent` / `wake_broadcast_failed`
3. السلوك الفعلي في snapshots:
   - `state.reason=before_hours`
   - `meta.next_wake_at`

### تفسير عملي

- **wake_boundary_reject قريب من بداية اليوم**: سلوك صحي غالبًا؛ cache القديمة لا تتجاوز boundary.
- **wake_broadcast_failed**: إشارة مباشرة لمشكلة في scheduler أو channels.
- **شاشات تبقى نائمة رغم وجود next_wake_at صحيح**: راجع wake scheduler أولًا ثم WS delivery.

## متى نكتفي بالبنية الحالية

ابقَ على البنية الحالية إذا تحققت أغلب هذه الشروط:

1. `hit_ratio >= 0.90`
2. `inline_build_ratio < 0.10`
3. `queue_wait_time_ms_avg < 150ms`
4. `soft_timeout` نادر أو صفر
5. `worker_unavailable = 0` خارج أوقات deploy
6. لا يوجد backlog مستمر في `snapshot_queue_depth`
7. wake failures غير ظاهرة في logs

إذا تحققت هذه الصورة، فالبنية الحالية **ما زالت كافية** ولا تحتاج فصل worker أو زيادة موارد مباشرة.

## متى نفصل `display_snapshot_worker`

افصل `display_snapshot_worker` عندما ترى **نمطًا مستمرًا** يجمع أكثر من إشارة، وليس إشارة واحدة فقط:

1. `inline_build_ratio > 0.25` بشكل متكرر
2. `queue_wait_time_ms_avg > 400ms`
3. `queue_wait_time_ms_max > 3000ms`
4. `soft_timeout` يتكرر يوميًا
5. `worker_unavailable` يحدث خارج نافذة deploy/restart
6. `snapshot_queue_depth` يبقى مرتفعًا لفترات ملحوظة
7. سجلات web تبدو مختلطة أو مزدحمة بسبب worker traffic بحيث يصعب التشخيص

**القرار العملي:**  
إذا اجتمعت 3 أو أكثر من هذه النقاط خلال مراجعتين أسبوعيتين متتاليتين، يصبح فصل `display_snapshot_worker` هو الخطوة التالية الأكثر منطقية.

## متى نفصل `display_wake_scheduler`

أولوية فصل `display_wake_scheduler` أقل من worker، لكن يصبح منطقيًا إذا ظهر واحد أو أكثر من التالي:

1. `wake_broadcast_failed` يتكرر
2. wake timing يتأخر أو يفشل رغم أن queue/build صحيان
3. نحتاج عزل wake loop عن restarts الخاصة بالـ web
4. نريد singleton واضح لمسؤولية wake broadcasts بدل embedded background loop

**القاعدة العملية:**  
لا تفصل wake scheduler أولًا. افصل snapshot worker أولًا إن احتجت، ثم أعد تقييم wake scheduler بعد استقرار البنية.

## متى نزيد workers أو خطة السيرفر

زيادة workers أو موارد الخدمة أنسب عندما تكون المشكلة **resource contention** داخل web أكثر من كونها queue design issue.

### مؤشرات زيادة web workers / plan

1. `inline_build_ratio` بدأ يرتفع
2. `soft_timeout` يظهر في builds inline
3. `ws_metrics` يظهر:
   - `connections_failed` مرتفعة
   - `broadcast_latency_avg_ms` مرتفعة
4. cache hit ratio ينخفض أثناء الذروة رغم أن worker حي وqueue wait مقبول

### مؤشرات زيادة موارد Redis / channels path

1. `redis_ping_ms` يرتفع بوضوح
2. queue wait يرتفع بدون تفسير من web CPU فقط
3. broadcast failures أو delays تتكرر

**القاعدة العملية:**  
- إذا كانت المشكلة أساسًا **inline builds + web responsiveness**: فكّر أولًا في زيادة web workers/plan.  
- إذا كانت المشكلة أساسًا **queue backlog + worker pressure**: فكّر أولًا في فصل worker.  
- إذا كانت المشكلة أساسًا **Redis / channels latency**: راجع Redis sizing/connectivity قبل أي refactor معماري.

## Production Monitoring Checklist

1. راقب `/api/display/metrics/` على فترات ثابتة.
2. راقب `snapshot_observability.snapshot_cache.hit/miss`.
3. احسب `hit_ratio` و`miss_ratio`.
4. راقب `snapshot_build.source.inline.count` مقابل `source.queue.count`.
5. راقب `snapshot_build.soft_timeout`.
6. راقب `snapshot_queue.queue_wait_time_ms_avg/max`.
7. راقب `snapshot_worker_alive`, `snapshot_worker_age_sec`, `snapshot_queue_depth`.
8. راقب `metrics:snapshot_queue:worker_unavailable`.
9. راقب logs التالية:
   - `event=snapshot_build_budget`
   - `event=snapshot_queue` مع `reason=worker_unavailable`
   - `event=snapshot_cache` مع `reason=older_revision`
   - `wake_broadcast_failed`
10. راقب `/api/display/ws-metrics/` إذا كان WS جزءًا مهمًا من التشغيل الحالي.

## Weekly Review Checklist

1. احسب متوسط `hit_ratio` للأسبوع.
2. احسب `inline_build_ratio`.
3. راجع أعلى `queue_wait_time_ms_max`.
4. راجع عدد `soft_timeout`.
5. راجع أي `worker_unavailable` خارج نافذة deploy.
6. راجع أي `wake_broadcast_failed`.
7. راجع هل backlog في `snapshot_queue_depth` كان transient أم persistent.
8. قارن الذروة بين أيام الدراسة وبداية اليوم وقبل/بعد active window.
9. قرر:
   - إبقاء البنية الحالية
   - زيادة web workers/plan
   - فصل snapshot worker
   - فصل wake scheduler لاحقًا

## قاعدة قرار مختصرة

### اكتفِ بالبنية الحالية إذا:

- cache hit ratio مرتفع
- inline builds قليلة
- queue wait منخفض
- لا يوجد soft timeouts متكررة
- worker مستقر

### زد موارد web إذا:

- inline builds ترتفع
- WS health يبدأ بالتراجع
- soft timeouts تظهر في inline path

### افصل `display_snapshot_worker` إذا:

- queue backlog مستمر
- inline build ratio مرتفع
- worker availability غير مستقرة
- build pressure صار يؤثر على web

### افصل `display_wake_scheduler` إذا:

- wake failures متكررة
- نحتاج عزل wake lifecycle عن web deploys
- snapshot worker أصبح منفصلًا واستقرت بقية البنية

## ملاحظة أخيرة

هذا الدليل لا يفترض أن كل threshold رقم جامد نهائي، لكنه يقدّم **baseline عملي**. القرار الأفضل دائمًا يكون من **نمط متكرر عبر الزمن**، لا من spike واحد أو deploy واحد.
