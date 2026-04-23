# Display Snapshot Observability

آخر تحديث: 2026-04-23

هذه الوثيقة تصف طبقة الـ observability المضافة لمسار `snapshot/cache` بدون تغيير topology التشغيلية أو routes العامة أو سلوك الشاشة.

## الهدف

- قياس `snapshot_cache` بشكل أوضح.
- معرفة متى يتم البناء inline ومتى يتم عبر queue ومتى يتم استخدام stale fallback.
- فهم كفاءة enqueue / dedupe / queue wait.
- جعل التشخيص من logs أسرع وأقل غموضًا.

## ما الذي أُضيف

- helper مركزي: `schedule.snapshot_observability`
  - counters موحدة عبر cache
  - structured logs بصيغة `key=value`
  - تجميع payload تشخيصي للـ metrics
- ربط helper داخل:
  - `schedule.api_views`
  - `schedule.snapshot_materializer`
- توسيع endpoint الداخلي الحالي:
  - `/api/display/metrics/`
  - تمت إضافة حقل `snapshot_observability`

لم تتم إضافة route جديدة في هذه الدفعة حتى لا يتغير surface التشغيلي الحالي.

## المقاييس الجديدة

### snapshot_cache

- `hit`
- `miss`
- `revision_reject`
- `wake_boundary_reject`

هذه المقاييس تقيس القرار النهائي لصلاحية cache entry، وليس فقط وجود المفتاح.

### snapshot_build

- `count`
- `duration_ms_sum`
- `duration_ms_max`
- `duration_ms_avg`
- `source.inline.count`
- `source.queue.count`
- `source.stale.count`

المصدر:

- `inline`: البناء داخل request path
- `queue`: البناء داخل worker / materializer
- `stale`: تم الرجوع إلى stale fallback بدل build جديد

### queue

- `enqueue_count`
- `skipped_enqueue`
- `deduplicated_jobs`
- `queue_wait_time_ms_sum`
- `queue_wait_time_ms_max`
- `queue_wait_time_ms_count`
- `queue_wait_time_ms_avg`

## كيف تُقرأ من endpoint

الـ endpoint الحالي:

- `/api/display/metrics/`

يعرض الآن:

- counters الخام القديمة
- الحقل المجمع: `snapshot_observability`

شكل تقريبي:

```json
{
  "metrics:snapshot_cache:hit": 42,
  "metrics:snapshot_build:count": 8,
  "snapshot_observability": {
    "snapshot_cache": {
      "hit": 42,
      "miss": 9,
      "revision_reject": 2,
      "wake_boundary_reject": 1
    },
    "snapshot_build": {
      "count": 8,
      "duration_ms_avg": 118,
      "source": {
        "inline": { "count": 3 },
        "queue": { "count": 4 },
        "stale": { "count": 1 }
      }
    },
    "queue": {
      "enqueue_count": 6,
      "skipped_enqueue": 5,
      "deduplicated_jobs": 3,
      "queue_wait_time_ms_avg": 74
    }
  }
}
```

## شكل الـ logs

الأحداث الأساسية:

- `event=snapshot_cache`
- `event=snapshot_build`
- `event=snapshot_queue`
- `event=snapshot_metrics`

أمثلة:

```text
event=snapshot_cache cache_key=snapshot:v9:school:12:day:2026-04-23 day_key=2026-04-23 layer=steady outcome=hit reason=none rev=204 school_id=12
event=snapshot_cache cache_key=snapshot:v9:school:12:day:2026-04-23 day_key=2026-04-23 layer=steady outcome=miss reason=older_revision rev=205 school_id=12
event=snapshot_build day_key=2026-04-23 rev=205 school_id=12 source=inline stage=start
event=snapshot_build day_key=2026-04-23 duration_ms=94 rev=205 school_id=12 source=inline stage=end result=built
event=snapshot_queue day_key=2026-04-23 decision=queued job_id=abc123 latest_rev=205 reason=request_miss rev=205 school_id=12
event=snapshot_queue day_key=2026-04-23 decision=dequeued job_id=abc123 latest_rev=205 queue_wait_ms=61 reason=dequeued rev=205 school_id=12
```

## كيف تُستخدم لاحقًا

- إذا ارتفع `snapshot_cache.miss` مع `snapshot_build.source.inline.count` فالمشكلة غالبًا أن queue لا تسبق الطلبات بما يكفي.
- إذا ارتفع `revision_reject` كثيرًا فهناك churn أعلى من المتوقع في revision أو تأخر في materialization.
- إذا ارتفع `wake_boundary_reject` قرب بداية اليوم فهذا يعني أن منطق wake boundary يعمل، ويمكن بعدها ضبط prewarm أو scheduler timing بدل تغيير cache semantics.
- إذا ارتفع `skipped_enqueue` و`deduplicated_jobs` مع queue wait منخفض، فالـ dedupe يعمل جيدًا.
- إذا ارتفع `queue_wait_time_ms_avg` مع زيادة `inline` builds، فقد تكون هذه إشارة لاحقة للحاجة إلى worker مستقل، لكن ليس بالضرورة الآن.

## ملاحظات الدفعة

- لا يوجد refactor واسع.
- لا يوجد فصل خدمات.
- لا يوجد تغيير في routes العامة الخاصة بالشاشة أو API contracts.
- الـ observability الحالية داخلية وتشخيصية فقط.
