# School Display — Phase 1: Cloudflare Edge Cache for `/api/display/snapshot/*`

## الهدف
تقليل عدد الطلبات الواصلة إلى السيرفر (Backend) من شاشات المدارس التي تستدعي:
- `GET /api/display/snapshot/`
- `GET /api/display/snapshot/<token>/`

مع الحفاظ على تحديث شبه لحظي وعدم تغيير منطق الواجهة الأمامية أو كسر الـ API.

## الفكرة المختصرة
- **Edge Cache على Cloudflare فقط لمدة ~10 ثوانٍ**.
- **منع Browser Cache** (حتى لا يعلق على بيانات قديمة على الجهاز).
- حصر الكاش في هذا الـ endpoint فقط.

> ملاحظة مهمة: في Cloudflare Free، تعيين **Edge TTL** مباشرة إلى أقل من ساعتين قد لا يكون متاحًا لبعض الإعدادات. الحل هنا هو استخدام **Edge TTL: Respect origin** والاعتماد على `Cache-Control` من السيرفر بقيمة قصيرة.

---

## ماذا يحدث قبل/بعد

### قبل
- كل شاشة تضرب السيرفر كل 10–20 ثانية.
- حتى لو كان عندك كاش داخلي في Django، ما زالت **كل الطلبات تصل للسيرفر**.

### بعد
- أول طلب خلال نافذة 10 ثوانٍ يصل للسيرفر.
- الطلبات التالية خلال نفس الـ 10 ثوانٍ تُخدم من Cloudflare (HIT) **بدون الوصول للسيرفر**.
- بعد انتهاء 10 ثوانٍ: أول طلب جديد يعيد تعبئة الكاش (MISS ثم يصبح HIT).

الناتج: انخفاض كبير في الضغط على السيرفر خصوصًا عندما يوجد عدة شاشات لنفس المدرسة.

مثال مبسط:
- 100 شاشة تستدعي كل 10 ثوانٍ ≈ 600 طلب/دقيقة إلى السيرفر.
- مع Edge Cache 10 ثوانٍ (لكل توكن/مدرسة) ≈ ~6 طلب/دقيقة (لكل PoP) بدل 600.

---

## تغييرات السيرفر (Backend)

تم ضبط الاستجابة الخاصة بـ endpoint `snapshot` لإرجاع هيدر كاش قصير:
- `Cache-Control: public, max-age=0, s-maxage=10`

المعنى:
- `max-age=0`: المتصفح لا يحتفظ بمحتوى صالح للاستخدام (أقصى شيء قد يخزن نسخة “stale” لا تُستخدم بدون إعادة جلب).
- `s-maxage=10`: السماح لـ Cloudflare Edge بالكاش لمدة 10 ثوانٍ.

وتجنب كاش أخطاء/طلبات `nocache=1` عبر:
- `Cache-Control: no-store`

التطبيق موجود في:
- `schedule/api_views.py` (الدالة `snapshot`)

قيمة الـ 10 ثوانٍ أصبحت قابلة للتغيير عبر متغير بيئة:
- `DISPLAY_SNAPSHOT_EDGE_MAX_AGE` (افتراضيًا `10`)

> لضمان عدم تجاوز الـ staleness المدة المحددة، تم كذلك جعل TTL للكاش الداخلي في السيرفر لا يتجاوز قيمة `DISPLAY_SNAPSHOT_EDGE_MAX_AGE`.

---

## إعداد Cloudflare (Cache Rules فقط، بدون Workers/Page Rules)

اذهب إلى:
**Cloudflare Dashboard → Caching → Cache Rules → Create rule**

### Rule: `Display Snapshot (Edge Cache)`
**When incoming requests match…**

استخدم تعبير (Expression) يطابق فقط هذا المسار:

```txt
(http.request.method eq "GET" and (http.request.uri.path eq "/api/display/snapshot/" or starts_with(http.request.uri.path, "/api/display/snapshot/")))
```

**Then… (Actions)**
1) **Cache eligibility**: اجعلها **Eligible for cache** (أو “Cache everything” حسب واجهة Cloudflare).
2) **Edge TTL**: اختر **Respect existing headers** (Respect Origin).
3) **Browser TTL**: اختر **Bypass cache** (أو 0 seconds).

### ملاحظات مهمة لتفادي أخطاء خطيرة
- لا تقم بتجاهل الـ query string في الكاش إذا كان التوكن يمر عبر `?token=...`.
  - تجاهل query string قد يسبب تسريب Snapshot بين مدارس مختلفة.
- هذا الـ rule يجب أن يكون **محدود جدًا** لهذا الـ endpoint فقط حتى لا يتأثر باقي الـ APIs.

---

## التحقق (Verification)

1) تحقق من الهيدر القادم من السيرفر (عبر Cloudflare):
- نفّذ طلبين متتالين على نفس الرابط (نفس token إن وُجد).
- راقب هيدر Cloudflare:
  - أول طلب غالبًا: `CF-Cache-Status: MISS`
  - خلال 10 ثوانٍ: `CF-Cache-Status: HIT`

### Troubleshooting سريع
- إذا ظهر `CF-Cache-Status: DYNAMIC` أو لا يظهر `Age` غالبًا:
  - راقب هل يوجد `Set-Cookie` في الاستجابة (أول طلب من جهاز جديد قد يرسل كوكي ربط جهاز).
  - تأكد أن Cache Rule مفعّل على `school-display.com` فقط و`GET` فقط وأنه مضبوط على **Respect origin**.

2) تحقق أن Browser لا يكاش:
- Cloudflare Browser TTL (Bypass) يجب أن يمنع المتصفح من الاحتفاظ بالاستجابة.

---

## تغيير مدة الكاش مستقبلًا (5s / 15s)

بدون تغيير الواجهة الأمامية:
- عدّل قيمة متغير البيئة على السيرفر:
  - `DISPLAY_SNAPSHOT_EDGE_MAX_AGE=5` أو `15`

وبما أن Cloudflare مضبوط على **Respect origin**، لا تحتاج لتعديل Edge TTL في Cloudflare عند تغيير القيمة على السيرفر.

---

## نطاق Phase 1 (حسب القيود)
- لا Workers
- لا Page Rules
- لا تغييرات على منطق الواجهة الأمامية
- لا تعديلات أمنية (Firewall/Tokens/Device Lock)
