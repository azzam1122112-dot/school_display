# Display System Architecture Overview

آخر تحديث: 2026-04-23

هذه الوثيقة تصف الوضع الحالي كما هو في الكود فقط. لم يتم التحقق من متغيرات بيئة Render الفعلية من لوحة Render، لذلك أي ملاحظة عن الإنتاج هنا مبنية على `render.yaml` والملفات المحلية، وليست تأكيدًا لحالة الخدمة المنشورة.

## نطاق الدفعة

- توثيق مسار شاشة العرض الحالي بدون refactor.
- تحديد مصدر الحقيقة لتدفق الشاشة، snapshot، WebSocket، revision، cache، queue، وwake/sleep.
- حصر legacy أو الازدواجيات الظاهرة من الكود.
- مراجعة `render.yaml` مقارنة بالبنية المحلية.

## ملخص تنفيذي

مصدر الحقيقة الحالي لشاشة العرض هو:

- الشاشة والمدرسة: `core.models.DisplayScreen` و`core.models.School`.
- إعدادات وجدول المدرسة: `schedule.models.SchoolSettings` وبقية موديلات `schedule`.
- صفحة العرض العامة: `website.views` مع القالب `templates/website/display.html`.
- Snapshot API الحقيقي: `schedule.api_views.snapshot` عبر `/api/display/snapshot/<token>/`.
- Status polling: `schedule.api_views.status` عبر `/api/display/status/<token>/`.
- WebSocket realtime: `display.consumers.DisplayConsumer` عبر `/ws/display/?token=<token>&dk=<device_id>`.
- Revision bump/invalidation: `schedule.signals` و`schedule.cache_utils`.
- Snapshot queue/worker: `schedule.snapshot_materializer` وأمر `display_snapshot_worker`.
- Wake scheduler: `schedule.wake_broadcaster` وأمر `display_wake_scheduler`.

## فتح الشاشة من short code أو token

المسارات العامة:

- `/s/<short_code>/` و`/s/<short_code>` معرفان في `website.urls`.
- `/?token=<token_or_short_code>` يمر عبر `website.views.home`.

التدفق:

1. `config.urls` يضمّن `website.urls` على الجذر `/`.
2. `website.views.short_display_redirect()` يستدعي `display_view()` ولا يعمل redirect للرابط الطويل.
3. `website.views._resolve_screen_and_settings()` يبحث في `core.DisplayScreen` عن `token__iexact` أو `short_code__iexact` مع `is_active=True`.
4. إذا كان الإدخال short code، يتم تحويله داخليًا إلى `screen.token`.
5. `website.views._build_display_context()` يمرر للقالب:
   - `api_token/display_token/token = effective_token`
   - `snapshot_url = /api/display/snapshot/<effective_token>/`
   - `school_id`
   - `schedule_revision`
6. `templates/website/display.html` يحمّل `static/js/display.js` الذي يبدأ fetch للـ snapshot ويفتح WebSocket لاحقًا إذا كان مفعّلًا.

ملاحظة مهمة: API وWebSocket يتوقعان token الحقيقي وليس short code. short code يُحل داخل صفحة `website` قبل أن تصل الواجهة إلى `/api/display/*`.

## تحميل snapshot

المسار الحقيقي:

- URL: `/api/display/snapshot/<token>/`
- `config.urls` -> `core.api_urls` -> `schedule.api_urls` -> `schedule.api_views.snapshot`

طبقات قبل الـ view:

- `core.middleware.SnapshotEdgeCacheMiddleware` ينظف cookies و`Vary: Cookie` لمسارات snapshot.
- `core.middleware.DisplayTokenMiddleware` يعمل على `/api/display/*` ويتحقق من token في المسار أو query أو header. نمطه يقبل 32/64 hex فقط، لذلك لا يعتمد على short code في API.

داخل `schedule.api_views.snapshot`:

1. يستخرج token من path/header/query.
2. لمسار `/api/display/snapshot/` يطلب device id من `X-Display-Device` أو `dk`.
3. ينفذ ربط الجهاز عبر `display.services.bind_device_atomic()`.
4. يستخدم `display:token_map:<token_hash>` لتسريع token -> school/screen.
5. يحاول قراءة school snapshot cache قبل البناء.
6. إذا لم يجد cache صالحًا، يستخدم `get_or_build_snapshot()`.
7. `get_or_build_snapshot()` يحاول:
   - القراءة من `snapshot:v9:school:<school_id>:day:<day>`.
   - استخدام queue async إذا كان worker حيًا.
   - الانتظار القصير لنتيجة worker.
   - fallback إلى stale snapshot.
   - أو inline build إذا كان fallback مفعّلًا.
8. البناء الفعلي يتم عبر `_build_snapshot_payload()` ثم `schedule.time_engine.build_day_snapshot()`.
9. الاستجابة تستخدم ETag وheaders مثل `X-Snapshot-Cache`, `X-Revision`, `X-School-Id`.

## Status polling

المسار الحقيقي:

- URL: `/api/display/status/<token>/`
- `config.urls` -> `core.api_urls` -> `schedule.api_urls` -> `schedule.api_views.status`

الدور:

- endpoint خفيف لا يبني snapshot.
- يقارن `v` أو `rev` من العميل مع `schedule_revision` الحالي.
- إذا revision متساوٍ يرجع 304.
- إذا تغير أو يوجد `display:force_refresh:<token_hash>` يرجع `fetch_required: true`.
- إذا يوجد `display:force_reload:<token_hash>` يرجع `reload: true`.
- يحافظ على device binding إذا وصل `dk` أو `X-Display-Device`.

## WebSocket connection

المسار الحقيقي:

- ASGI: `config.asgi.application`
- Routing: `display.routing.websocket_urlpatterns`
- URL: `/ws/display/?token=<token>&dk=<device_id>`
- Consumer: `display.consumers.DisplayConsumer`

التدفق:

1. `config.asgi` يستخدم `ProtocolTypeRouter`.
2. WebSocket يمر عبر `AllowedHostsOriginValidator` و`AuthMiddlewareStack`.
3. `DisplayConsumer.connect()` يقرأ `token` و`dk`.
4. يرفض الاتصال إذا كان token أو `dk` مفقودًا.
5. ينفذ `bind_device_atomic(token, device_id)`.
6. يشتق group من السيرفر فقط:
   - مدرسة: `school_<school_id>` عبر `display.ws_groups.school_group_name`.
   - شاشة/token: `token_<hash>` عبر `display.ws_groups.token_group_name`.
7. ينضم إلى school group للتحديثات العامة، وإلى token group للأوامر اليدوية.
8. يرسل heartbeat دوريًا، ويتعامل مع `ping/pong`.

أحداث WebSocket المهمة:

- `broadcast_invalidate` يرسل للعميل `{type: "snapshot_refresh", revision, reason}`.
- `broadcast_reload` يرسل `{type: "reload"}`.
- `broadcast_patch` موجود كامتداد حالي لكنه ليس المصدر الأساسي لتحديث الشاشة.

## Schedule revision bump

مصدر الحقيقة:

- `schedule.cache_utils.bump_schedule_revision_for_school_id()`
- `schedule.cache_utils.bump_schedule_revision_for_school_id_debounced()`
- `schedule.signals._bump_and_invalidate()`

الموديلات التي تؤثر على snapshot حسب الإشارات:

- `schedule.SchoolSettings`
- `schedule.DaySchedule`
- `schedule.Period`
- `schedule.Break`
- `schedule.ClassLesson`
- `schedule.SchoolClass`
- `schedule.Subject`
- `schedule.Teacher`
- `schedule.DutyAssignment`
- `notices.Announcement`
- `notices.Excellence`
- `standby.StandbyAssignment`
- `core.School`

التدفق:

1. post_save/post_delete يستدعي `_bump_and_invalidate()`.
2. يتم bump للـ `schedule_revision` مع debounce قصير.
3. يتم تحديث cache الخاص بالrevision.
4. يتم invalidation للـ snapshot caches المرتبطة بالمدرسة.
5. يتم ضبط force refresh لكل tokens النشطة في المدرسة.
6. بعد commit يتم إرسال WebSocket invalidate.
7. بعد commit يتم enqueue لبناء snapshot إذا كان async queue متاحًا والworker حيًا.

## Snapshot invalidation

مصدر الحقيقة:

- `schedule.cache_utils.invalidate_display_snapshot_cache_for_school_id()`
- `schedule.signals._arm_force_refresh_for_school()`
- `schedule.signals._broadcast_invalidate_ws()`

المفاتيح المهمة:

- `display:school_rev:<school_id>`
- `display:token_map:<token_hash>`
- `display:force_refresh:<token_hash>`
- `display:force_reload:<token_hash>`
- `snapshot:v9:school:<school_id>:day:<YYYY-MM-DD>`
- `snapshot:last:<school_id>:<YYYY-MM-DD>`
- مفاتيح legacy يتم حذف نافذة منها مثل `snapshot:v7`, `snapshot:v8`, و`display:snap:v7`.

ملاحظة: `snapshot:v9` الحالي revision-agnostic في اسم المفتاح رغم أن الدالة تستقبل `rev`. revision يبقى داخل payload/meta ومسار القرار، وهذه نقطة مهمة للدفعات القادمة عند تحسين cache flow.

## Snapshot queue / worker

مصدر الحقيقة:

- Queue helpers: `schedule.snapshot_materializer`
- Worker command: `schedule.management.commands.display_snapshot_worker`

التدفق:

1. `get_or_build_snapshot()` أو `schedule.signals` يستدعيان `enqueue_snapshot_build()`.
2. queue يستخدم Redis، ويفضل `REDIS_CHANNELS_URL` إن وجد، وإلا cache Redis.
3. اسم queue الافتراضي: `display:snapshot:build:queue`.
4. يوجد dedupe/debounce/coalescing:
   - `display:snapshot:queue:pending:<school_id>:<day>`
   - `display:snapshot:latest_rev:<school_id>:<day>`
   - `display:snapshot:debounce:<school_id>:<day>`
5. worker ينفذ `dequeue_snapshot_build()` ثم `materialize_snapshot_for_school()`.
6. النتيجة تخزن school snapshot وstale fallback.
7. worker heartbeat محفوظ في `display:snapshot:worker:heartbeat`.

## Wake / sleep / idle flow

Server side:

- `schedule.time_engine.build_day_snapshot()` يحدد:
  - `meta.is_active_window`
  - `meta.active_window`
  - `meta.next_wake_at`
  - `state.reason` مثل `before_hours`, `after_hours`, `holiday`
- `schedule.wake_broadcaster.compute_active_start_for_today()` يحسب active_start.
- `schedule.wake_broadcaster.maybe_fire_pre_active_wake()` يرسل reload مرة واحدة قبل active_start.
- `display_wake_scheduler` يمسح كل `SchoolSettings` دوريًا ويستدعي broadcaster.

Client side:

- `static/js/display.js` هو مصدر منطق النوم/الاستيقاظ في المتصفح.
- يعتمد على snapshot meta و`next_wake_at`.
- أثناء النوم يقلل/يوقف polling حسب الحالة، ويستخدم wake timers وWebSocket reload/invalidate عندما يكون ذلك متاحًا.

## الملفات الأساسية حسب المسؤولية

- Screen lifecycle:
  - `core.models.DisplayScreen`
  - `dashboard.views_screens`
  - `core.screen_limits`
  - `website.views`
- School isolation:
  - `core.models.School`
  - `schedule.models.SchoolSettings`
  - `display.ws_groups.school_group_name`
  - `schedule.api_views.snapshot/status`
  - `dashboard.middleware` و`core.middleware.ActiveSchoolMiddleware`
- Device binding:
  - `display.services.device_binding`
  - `schedule.api_views.snapshot/status`
  - `display.consumers.DisplayConsumer`
  - `dashboard.views_screens.screen_unbind_device`
- Snapshot build:
  - `schedule.api_views._build_snapshot_payload`
  - `schedule.api_views._build_final_snapshot`
  - `schedule.time_engine.build_day_snapshot`
  - `schedule.snapshot_materializer.materialize_snapshot_for_school`
- Cache usage:
  - `schedule.api_views`
  - `schedule.cache_utils`
  - `display.cache_utils`
  - `display.services`
- Redis channels / WebSocket:
  - `config.asgi`
  - `config.settings.CHANNEL_LAYERS`
  - `display.routing`
  - `display.consumers`
  - `schedule.signals`
  - `schedule.wake_broadcaster`

## Legacy وازدواجيات ظاهرة

هذه عناصر لا يجب حذفها ضمن هذه الدفعة:

- `schedule.api_display.snapshot` wrapper legacy يشير إلى `schedule.api_views.snapshot`.
- `dashboard.api_display.display_snapshot` يبدو API قديمًا لبناء snapshot مختلف، ولا يظهر ضمن URL routing الحالي حسب البحث المحلي.
- `core.models.SchoolSubscription` موثق داخل الكود كـ legacy، بينما مصدر الحقيقة الحالي للاشتراكات يبدو `subscriptions.SchoolSubscription`.
- migrations قديمة في `schedule` أنشأت ثم حذفت `schedule.DisplayScreen`; الموديل الحالي هو `core.DisplayScreen`.
- `schedule.views.display_screen()` يشير إلى قالب `schedule/display.html`، ولا يظهر مسار URL حالي يستدعيه في `schedule.urls`.
- `core.middleware.DisplayTokenMiddleware` يحتوي منطق binding/cache قديم لمسارات API، لكن snapshot/status يعيدان التحقق داخليًا عبر `display.services.bind_device_atomic`. هذا ازدواج حماية وليس مرشح حذف فوريًا.
- `schedule.api_urls` يحتفظ aliases:
  - `/api/display/today/`
  - `/api/display/live/`
  وكلاهما يوجهان إلى `schedule.api_views.snapshot` للتوافق الخلفي.

## مراجعة render.yaml

الوضع الموثق في `render.yaml`:

- Redis service للكاش: `school-display-redis` مع `allkeys-lru`.
- Redis service للقنوات: `school-display-channels-redis` مع `noeviction`.
- Web service واحد باسم `school-display`.
- build:
  - `pip install --upgrade pip`
  - `pip install -r requirements.txt`
  - `python manage.py collectstatic --noinput`
- start:
  - `python manage.py migrate --noinput`
  - إنشاء superuser اختياري عبر env vars
  - تشغيل `display_snapshot_worker` داخل web process إذا `DISPLAY_START_EMBEDDED_SNAPSHOT_WORKER=True`
  - تشغيل `display_wake_scheduler` داخل web process إذا `DISPLAY_START_EMBEDDED_WAKE_SCHEDULER=True`
  - تشغيل Gunicorn ASGI عبر `uvicorn.workers.UvicornWorker`

الفروقات/المخاطر التشغيلية المرصودة:

- لا توجد خدمة worker مستقلة في `render.yaml`; العاملان يعملان embedded داخل web process. هذا يعمل لكنه يزيد مسؤوليات web process.
- `render.yaml` يحتوي safeguard يخفض `WORKERS=1` إذا لم توجد Redis cache URL، لكن `config.settings` يرفع `ValueError` إذا لم توجد Redis cache/channels URL. على Render الحالي، env vars معرفة من خدمات Redis في yaml، لذلك لا يظهر التعارض عمليًا إذا طُبّق yaml كما هو. لا يمكن تأكيد بيئة Render الفعلية من الكود المحلي.
- `DISPLAY_SNAPSHOT_INLINE_FALLBACK` في `render.yaml=False` بينما default في `config.settings=True`. هذا يعني أن الإنتاج حسب yaml يفضل async worker/building payload أكثر من بيئة محلية بدون env. يجب الانتباه عند الاختبار المحلي.
- `DISPLAY_REQUIRE_REDIS_SPLIT=True` في `render.yaml`، بينما default في settings هو False. يلزم مراجعة `core.redis_topology` في دفعة التشغيل إذا أردنا فرض أو فحص هذا الشرط.
- WebSockets تعتمد على تشغيل ASGI (`config.asgi`) وRedis channels؛ `render.yaml` يستخدم Gunicorn + UvicornWorker وهذا مناسب للمسار الحالي.

## أوامر تشغيل وفحص مفيدة

تشغيل dev محليًا يتطلب Redis env صالحًا لأن `config.settings` يرفض غياب Redis:

```powershell
python manage.py check
python manage.py display_snapshot_worker --once
python manage.py display_wake_scheduler --once
```

على Render، الأوامر الفعلية موثقة في `render.yaml`، وأي فصل للعاملين إلى services مستقلة يجب أن يكون ضمن دفعة تشغيلية منفصلة مع خطة تراجع.

## نقاط تحتاج انتباه في الدفعات التالية

- توحيد قرار cache حول `snapshot:v9` وrevision؛ الاسم الحالي لا يتضمن revision رغم أن عدة دوال تمرر rev.
- توضيح topology تشغيل worker/scheduler: embedded الآن، وفصلهما يحتاج دفعة مستقلة.
- حصر legacy APIs القديمة قبل حذف أي شيء، خصوصًا `dashboard.api_display` وaliases `today/live`.
- مراجعة ازدواج device binding بين middleware وsnapshot/status/WS دون كسر الحماية الحالية.
