# Display Runtime Topology

آخر تحديث: 2026-04-23

هذه الوثيقة تخص **الدفعة 2 فقط**: توضيح البنية التشغيلية الحالية وتقليل الـ drift بين `render.yaml` والسلوك الفعلي في الكود، بدون refactor واسع وبدون تغيير routes أو API contracts أو منطق العرض.

## الهدف

- تحديد ما الذي يعمل اليوم داخل خدمة `web`.
- توضيح ما الذي يجب أن يبقى داخل `web process`.
- توضيح ما الذي يمكن فصله لاحقًا إلى worker أو scheduled/background service.
- تثبيت أقل خطوة آمنة الآن بدون فصل فعلي للخدمات.

## الملخص التنفيذي

الوضع الحالي على مستوى الكود و`render.yaml` هو:

| المكوّن | الوضع الحالي | الملاحظات التشغيلية |
| --- | --- | --- |
| `school-display` web service | موجود | يشغّل Django ASGI + Gunicorn/Uvicorn، وهو نقطة HTTP وWebSocket الوحيدة |
| `display_snapshot_worker` | **embedded داخل خدمة web** | يُشغَّل كعملية خلفية child process من `startCommand`، وليس خدمة Render مستقلة |
| `display_wake_scheduler` | **embedded داخل خدمة web** | يُشغَّل كعملية خلفية child process من `startCommand`، وليس خدمة Render مستقلة |
| Redis cache | مستقل | مصدر cache الرئيسي وsnapshot cache |
| Redis channels | مستقل | مصدر Channels/WebSocket layer، والـ snapshot queue تفضله عند توفره |

النتيجة: المشروع اليوم يعمل كتوبولوجيا **single web service + 2 embedded background processes + 2 Redis services**.

## ماذا يعمل اليوم داخل خدمة `web`

داخل `render.yaml`، `startCommand` ينفذ الترتيب التالي:

1. `python manage.py migrate --noinput`
2. إنشاء superuser اختياري
3. تشغيل `display_snapshot_worker` في الخلفية إذا كانت `DISPLAY_START_EMBEDDED_SNAPSHOT_WORKER=True`
4. تشغيل `display_wake_scheduler` في الخلفية إذا كانت `DISPLAY_START_EMBEDDED_WAKE_SCHEDULER=True`
5. تشغيل Gunicorn باستخدام `config.asgi:application`

هذا يعني أن:

- العاملان **ليسَا داخل Gunicorn worker process** نفسه.
- لكنهما **مرتبطان مباشرة بعمر خدمة web** لأن shell نفسه هو من يطلقهما ويوقفهما.
- إذا تعطلت خدمة `web` أو أُعيد نشرها، يتوقف العاملان معها ثم يعاد تشغيلهما معها.

## ماذا يجب أن يبقى داخل `web process`

هذه العناصر يجب أن تبقى ضمن خدمة `web`:

- Django HTTP/ASGI app عبر `config.asgi`.
- endpoints الخاصة بـ:
  - `/api/display/snapshot/<token>/`
  - `/api/display/status/<token>/`
- WebSocket endpoint `/ws/display/`
- signal handlers وrevision invalidation وqueue producers.
- أي fallback inline متعلق بطلب snapshot نفسه عندما يقرر الكود البناء من مسار الطلب.

السبب: هذه العناصر جزء من request/response path أو من realtime path، وفصلها الآن سيغيّر topology التشغيلية أكثر من المطلوب في هذه الدفعة.

## ما الذي يعمل embedded اليوم لكنه ليس جزءًا أصيلًا من `web`

### `display_snapshot_worker`

المسؤولية:

- سحب وظائف بناء snapshot من Redis queue.
- materialize للـ snapshot cache.
- إرسال heartbeat على المفتاح `display:snapshot:worker:heartbeat`.

الاستنتاج التشغيلي:

- هذا المكوّن **worker فعلي** وليس web concern.
- وجوده الحالي داخل خدمة `web` هو قرار تشغيل مؤقت لتقليل عدد الخدمات، وليس حدودًا معمارية لازمة.

### `display_wake_scheduler`

المسؤولية:

- مسح `SchoolSettings` دوريًا.
- حساب pre-active wake window.
- بث `reload` عبر WebSocket عند الحاجة.

الاستنتاج التشغيلي:

- هذا المكوّن **scheduler/background loop** وليس web concern.
- وجوده embedded داخل `web` اليوم مريح، لكنه ليس المكان المثالي طويل المدى.

## علاقة Redis الحالية

### Redis cache

يُستخدم من أجل:

- Django cache backend
- snapshot cache
- revision cache
- wake dedupe
- snapshot worker heartbeat

### Redis channels

يُستخدم من أجل:

- `CHANNEL_LAYERS` الخاصة بالـ WebSocket
- snapshot build queue عند توفر `REDIS_CHANNELS_URL`

### ملاحظة مهمة

`schedule.snapshot_materializer` يفضّل `REDIS_CHANNELS_URL` للـ queue، ثم يعود إلى cache Redis فقط إذا لم توجد قناة مستقلة. لذلك الفصل بين Redis cache وRedis channels ليس تجميليًا فقط؛ بل هو جزء من topology التشغيلية المقصودة.

## الـ drift الحالي بين `render.yaml` والكود

### 1. Redis مطلوب فعليًا عند الإقلاع

في `config.settings`:

- `REDIS_CACHE_URL` و`REDIS_CHANNELS_URL` يُحسَبان عند import settings.
- إذا غاب أحدهما، يحصل:

```python
raise ValueError("Redis URLs are not configured properly")
```

لذلك:

- التحذير الموجود في `render.yaml` عن تخفيض `WORKERS=1` مفيد فقط لمسألة cache coherence.
- لكنه **ليس fallback حقيقيًا** إذا كانت Redis URLs مفقودة بالكامل، لأن Django لن يقلع أصلًا.

### 2. Default محلي يختلف عن Render

- `DISPLAY_SNAPSHOT_INLINE_FALLBACK` default في `config.settings` هو `True`.
- بينما `render.yaml` يضبطه إلى `False`.

تشغيليًا هذا يعني أن:

- البيئة الموصوفة في Render تعتمد أكثر على async queue + worker liveness.
- البيئة المحلية بدون env مطابق قد تتصرف بشكل مختلف وتسمح ببناء inline أكثر.

### 3. فرض split بين Redis موجود في Render وليس default في settings

- `render.yaml` يضبط `DISPLAY_REQUIRE_REDIS_SPLIT=True`.
- `config.settings` default لهذا المتغير هو `False`.

هذا لا يغيّر مسار التشغيل مباشرة، لكنه يغيّر شدة التنبيه في `core.apps` عند اكتشاف Redis shared topology.

## المخاطر التشغيلية الحالية

### 1. اقتران lifecycle الخلفية بعمر خدمة `web`

إذا توقف `web`, يتوقف معه:

- snapshot worker
- wake scheduler

وهذا يعني أن health الخاصة بالـ web لا تكفي وحدها للحكم على سلامة جميع loops الخلفية.

### 2. عدم وجود health surface مستقلة للعاملين embedded

`render.yaml` يعرّف health check واحدة على `/`.

لكن:

- يمكن أن يبقى Gunicorn حيًا
- بينما `display_snapshot_worker` أو `display_wake_scheduler` يكونان قد توقفا

وفي هذه الحالة ستبقى خدمة web "صحية" من منظور Render رغم وجود تدهور وظيفي جزئي.

### 3. تنافس على CPU والذاكرة داخل نفس الخدمة

خدمة web الواحدة تتحمل معًا:

- HTTP requests
- WebSocket connections
- snapshot queue processing
- wake scanning

هذا مقبول في topology صغيرة، لكنه يزيد خطر resource contention عند ارتفاع الضغط.

### 4. logs مختلطة في نفس service

سجلات:

- Gunicorn/ASGI
- snapshot worker
- wake scheduler

تخرج من نفس service stream، وهذا يصعب التشخيص السريع للأعطال التشغيلية.

### 5. restart أو deploy واحد يؤثر على كل الأدوار

أي deploy أو restart لخدمة web يقطع في نفس اللحظة:

- مسار HTTP/WS
- materialization background
- wake broadcasts

هذا يوسّع نطاق الأثر مقارنةً بتوبولوجيا مفصولة.

### 6. `display_snapshot_worker` أكثر حساسية من `display_wake_scheduler`

لأن `render.yaml` يضبط:

- `DISPLAY_SNAPSHOT_ASYNC_BUILD=True`
- `DISPLAY_SNAPSHOT_INLINE_FALLBACK=False`

فإن بقاء worker حيًا أهم تشغيليًا من بقاء wake scheduler حيًا. scheduler مهم، لكن تعطل worker أخطر مباشرة على snapshot freshness ومسار الـ miss.

## ما الذي يمكن فصله لاحقًا بدون كسر

### مرشح أول: `display_snapshot_worker`

هذا أفضل مرشح لأول فصل آمن لاحقًا، لأنه:

- يملك حدود مسؤولية واضحة.
- يعمل أصلًا عبر Redis queue + heartbeat.
- لا يحتاج أن يكون جزءًا من request path.

الفصل المتوقع لاحقًا:

- إنشاء Render worker/background service مستقلة تشغّل:

```bash
python manage.py display_snapshot_worker --poll-timeout=5
```

- ثم ضبط `DISPLAY_START_EMBEDDED_SNAPSHOT_WORKER=False` داخل web بعد التأكد من heartbeat.

### مرشح ثانٍ: `display_wake_scheduler`

يمكن فصله لاحقًا إلى:

- background worker واحدة
- أو scheduled/cron-style service إذا تم الحفاظ على نفس semantics

لكن أولوية فصله أقل من snapshot worker لأن:

- wake path محمي بـ dedupe في Redis
- scheduler loop أخف
- أثر تعطله عادة أقل مباشرة من worker

## هل المشروع يحتاج worker service مستقلة الآن؟

**ليس كخطوة تنفيذية في هذه الدفعة، لكن نعم كاتجاه تشغيلي قريب**.

التقدير الحالي:

- إذا كانت الخدمة ما زالت صغيرة أو تعمل على instance واحدة، فالإبقاء على worker embedded الآن ما زال مقبولًا.
- لكن بما أن async snapshot build معتمد وinline fallback معطّل في Render، فوجود worker مستقل لاحقًا سيخفض المخاطر بشكل واضح.

لذلك القرار الأنسب هو:

- **الآن:** إبقاء worker embedded وعدم كسر topology.
- **لاحقًا:** فصل `display_snapshot_worker` أولًا.
- **بعده:** تقييم فصل `display_wake_scheduler` كخدمة singleton مستقلة.

## أقل خطوة آمنة الآن

أقل خطوة آمنة في الدفعة 2 هي:

1. توثيق topology الحالية بوضوح.
2. تثبيت أن العاملين embedded داخل خدمة `web` وليسَا خدمات مستقلة.
3. توضيح أن فصل `display_snapshot_worker` هو الخطوة التالية الأكثر أمانًا.
4. الإبقاء على `display_wake_scheduler` embedded حاليًا.
5. عدم تغيير أي routes أو API contracts أو display logic.

## التوصية المرحلية

### هذه الدفعة

- لا فصل فعلي للخدمات.
- فقط توثيق وتشذيب تشغيل `render.yaml` تعليقًا وبنيةً.

### الدفعة التالية المناسبة للفصل

1. إضافة خدمة مستقلة لـ `display_snapshot_worker`.
2. إبقاء web service مسؤولة فقط عن HTTP/ASGI/WebSocket والـ queue producers.
3. تعطيل embedded snapshot worker من web بعد إثبات worker heartbeat.

### خطوة لاحقة بعد ذلك

1. فصل `display_wake_scheduler` إلى singleton background service.
2. تعطيل embedded wake scheduler من web.
3. إضافة مراقبة أو health تشغيلية أوضح لهذا المسار.

## أوامر مفيدة للفحص والتشغيل

محليًا، لأن `config.settings` يطلب Redis URLs، يمكن استخدام env placeholders للفحص البنيوي:

```powershell
$env:REDIS_CACHE_URL='redis://localhost:6379/0'
$env:REDIS_CHANNELS_URL='redis://localhost:6379/1'
python manage.py check
python manage.py print_cache_config
python manage.py display_snapshot_worker --once --poll-timeout=1
python manage.py display_wake_scheduler --once --interval=60 --lead-minutes=30 --window-seconds=90
```

هذه الأوامر تثبت صحة wiring البنيوي محليًا، حتى لو لم تكن Redis المحلية متاحة فعليًا.
