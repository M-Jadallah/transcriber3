# النشر على Coolify — ملاحظات سريعة

هذا المستند يلخّص الخطوات العملية لنشر حزمة التطبيق على Coolify بعد رفع المستودع.

## 1) المتطلبات قبل النشر

- خادم Coolify يعمل ويستطيع الوصول إلى الإنترنت لسحب صور Docker الرسمية.
- نطاق (domain) مُوجّه بعنوان DNS إلى خادم Coolify، مثال: `tafreeg.example.com`.
- مفاتيح Deepgram صالحة لخمسة عمليات تفريغ متوازية (واحدة لكل عامل).
- (اختياري) حساب OpenAI/ChatGPT لتفعيل ميزة التنسيق بالذكاء الاصطناعي.

## 2) رفع المستودع

في Coolify:
1. أنشئ مشروعًا جديدًا باسم `tafreeg` (أي اسم تفضّله).
2. اختر **Docker Compose** كنوع مورد.
3. اربط المستودع (Git) أو ارفع ملف `transcriber-app-fixed.zip` كمصدر.
4. سيكتشف Coolify تلقائيًا ملف `docker-compose.yml` في جذر المستودع.

## 3) تعيين الخدمة الرئيسية (Main Service)

- في صفحة الـ Compose، اضبط **Service Name** على `gateway`.
- اضبط **Port** على `80`.
- اضبط **Domain** على نطاقك (مثال: `https://tafreeg.example.com`).

## 4) متغيرات البيئة (Environment Variables)

### متغيرات يولّدها Coolify تلقائيًا (لا تضعها يدويًا):

- `SERVICE_PASSWORD_64_POSTGRES`
- `SERVICE_PASSWORD_64_REDIS`
- `SERVICE_PASSWORD_64_ADMIN`
- `SERVICE_PASSWORD_64_OPENCODE`
- `SERVICE_HEX_128_SESSION`

### متغيرات يجب أن تضعها يدويًا في Coolify:

| المتغير | القيمة |
|---|---|
| `APP_URL` | `https://tafreeg.example.com` (نطاقك) |
| `APP_VERSION` | `1.0.0` |
| `APP_ENV` | `production` |
| `TZ` | `Asia/Amman` |
| `LOG_LEVEL` | `INFO` |
| `ADMIN_USERNAME` | `admin` |
| `POSTGRES_DB` | `youtube_transcriber` |
| `POSTGRES_USER` | `youtube_transcriber` |
| `TRUSTED_HOSTS` | `tafreeg.example.com` (نطاقك فقط، بدون https://) |
| `GATEWAY_NETWORK_SUBNET` | `172.29.0.0/24` (اترك الافتراضي) |
| `GATEWAY_PEER_IP` | `172.29.0.2` (اترك الافتراضي) |
| `DEFAULT_LANGUAGE` | `ar` |
| `DEFAULT_DEEPGRAM_MODEL` | `whisper-large` |
| `DEEPGRAM_API_KEY_WORKER_1` | مفتاح Deepgram الأول |
| `DEEPGRAM_API_KEY_WORKER_2` | مفتاح Deepgram الثاني |
| `DEEPGRAM_API_KEY_WORKER_3` | مفتاح Deepgram الثالث |
| `DEEPGRAM_API_KEY_WORKER_4` | مفتاح Deepgram الرابع |
| `DEEPGRAM_API_KEY_WORKER_5` | مفتاح Deepgram الخامس |
| `OPENCODE_SERVER_USERNAME` | `opencode` |
| `OPENCODE_VERSION` | `1.18.8` |
| `FORMATTING_DEFAULT_MODEL` | `openai/gpt-5.6-sol` |
| `FORMATTING_DEFAULT_REASONING` | `high` |

> جميع متغيرات `FORMATTING_*` لها قيم افتراضية معقولة في `docker-compose.yml`، يمكنك تركها أو تخصيصها حسب الحاجة.

## 5) الإطلاق الأول

1. اضغط **Deploy** في Coolify.
2. ستُبنى الصور الثلاث بالترتيب:
   - `backend` (Dockerfile): واجهة FastAPI + عمّال Celery.
   - `backend-formatting` (Dockerfile.formatting): خدمة OpenCode + عامل التنسيق.
   - `frontend` (Dockerfile): Nginx + ملفات الواجهة الثابتة.
3. سيُشغّل Coolify خدمة `migrate` (واحدة) لتطبيق ترحيلات Alembic.
4. ثم تُطلق باقي الخدمات الـ 15.

## 6) فحص الصحة (Health Checks)

- جميع الخدمات لها `healthcheck` مُعرّف.
- لو فشلت خدمة `api` في health check، تحقّق من:
  - `TRUSTED_HOSTS` تطابق النطاق الفعلي.
  - `APP_URL` تبدأ بـ `https://` أو `http://` حسب إعداد Coolify.
  - خدمة `postgres` سليمة (حالة `healthy`).
- لو فشل عامل Celery في health check، تحقّق من `REDIS_URL` و `DATABASE_URL`.

## 7) تسجيل الدخول لأول مرة

- بعد نجاح النشر، افتح `https://tafreeg.example.com` في المتصفح.
- سجّل الدخول باستخدام `ADMIN_USERNAME` وكلمة المرور التي أنشأها Coolify
  (ستجدها في متغير `SERVICE_PASSWORD_64_ADMIN`).

## 8) تفعيل التنسيق بالذكاء الاصطناعي (اختياري)

1. اذهب إلى **الإعدادات** في الواجهة.
2. اضغط **بدء ربط الحساب** في بطاقة ChatGPT/OpenCode.
3. أكمل مصادقة OAuth في الصفحة المنبثقة.
4. ارجع إلى صفحة الإعدادات واضغط **تحديث الحالة**.
5. ارفع ملف مهارة بصيغة ZIP من صفحة **مهارات التنسيق**.

## 9) النسخ الاحتياطي

البيانات الدائمة موجودة في أحجام Docker التالية:
- `postgres-data`: قاعدة البيانات (الأهم).
- `formatting-data`: ملفات المهارات والإعدادات.
- `formatting-jobs-data`: نتائج مهام التنسيق الدائمة.
- `audio-data`, `exports-data`: ملفات صوتية وصادرات (تُحذف تلقائيًا بعد 24 ساعة).

خذ نسخة احتياطية دورية من `postgres-data` على الأقل.

## 10) استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| فشل البناء في `frontend` | تأكد أن `frontend/package-lock.json` موجود وغير معدّل. |
| فشل `migrate` | راجع سجلّات `migrate`؛ تحقّق من `DATABASE_URL`. |
| `api` يعيد 401 دائمًا | كلمة مرور `ADMIN` في `SERVICE_PASSWORD_64_ADMIN` غير مضبوطة. |
| `worker-N` لا يستلم مهامًا | تحقّق من `REDIS_URL` و `DEEPGRAM_API_KEY_WORKER_N`. |
| التنسيق يفشل | تأكد أن خدمة `opencode-runtime` سليمة وأن حساب OpenAI مرتبط. |

## 11) تحديث التطبيق

لتحديث الكود:
1. ادفع التعديلات إلى المستودع.
2. في Coolify، اضغط **Deploy** مرة أخرى.
3. Coolify سيعيد بناء الصور المتأثرة فقط ويعيد تشغيل الخدمات.

---

للاطلاع على التفاصيل الكاملة للمعمارية، راجع `APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md`.
