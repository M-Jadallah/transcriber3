# متغيرات Coolify للنشر الموحّد

استخدم ملف النشر:

```text
docker-compose.yml
```

## القيم التي تدخلها يدويًا

انسخ محتوى `.env.coolify.manual.example` إلى **Environment Variables → Developer view**، ثم غيّر:

```env
APP_URL=https://your-domain.example.com
TRUSTED_HOSTS=your-domain.example.com
ADMIN_USERNAME=admin
DEEPGRAM_API_KEY_WORKER_1=...
DEEPGRAM_API_KEY_WORKER_2=...
DEEPGRAM_API_KEY_WORKER_3=...
DEEPGRAM_API_KEY_WORKER_4=...
DEEPGRAM_API_KEY_WORKER_5=...
```

خصص قيمة اعتماد مستقلة لكل عامل؛ يمرر Compose كل متغير إلى عامله المطابق فقط،
ولا يوزع أي مفتاح Deepgram على API أو بقية الخدمات.

تتضمن أمثلة البيئة `FORMATTING_INPUT_MAX_BYTES=20971520` و
`FORMATTING_STORAGE_MAX_BYTES=21474836480`. يمرر Compose القيمتين إلى `api`
و`formatting-worker` لأنهما يحمّلان إعداد التنسيق ويطبقان فحوص الإدخال والتخزين.

ملف الإنتاج يثبت `COOKIE_SECURE=true` ولا ينشر أي Host port. كما يرفض البدء من
دون `APP_URL` و`TRUSTED_HOSTS` ومفاتيح Deepgram الخمسة. اربط الدومين بخدمة
`gateway` فقط؛ التشغيل المحلي غير مدعوم بملف الإنتاج كما هو، ويحتاج Override
منفصلًا وIngress محليًا وأسرارًا يدوية خاصة لا تستخدم أسماء أسرار Coolify.

## بوابة الشبكة الثابتة

تستخدم البوابة شبكة `edge` العامة وحدها للوصول إلى Proxy المنصة، وشبكة
`gateway` داخلية مشتركة مع API. يثق Uvicorn فقط بعنوان البوابة المحدد هنا:

```env
GATEWAY_NETWORK_SUBNET=172.29.0.0/24
GATEWAY_PEER_IP=172.29.0.2
```

يجب أن يكون `GATEWAY_PEER_IP` عنوان Host صالحًا داخل
`GATEWAY_NETWORK_SUBNET` وألا يتعارض مع شبكة أخرى في المضيف. دعم Coolify لـIPAM
والعنوان الساكن في إصدارك **بوابة تشغيل إلزامية غير متحققة**: اختبر النشر في
Staging وتحقق من احتفاظ حاوية `gateway` بالعنوان المحدد قبل قبول الإنتاج. إذا
احتاجت بيئة المضيف نطاقًا آخر فغيّر القيمتين معًا؛ لا توسع
`--forwarded-allow-ips` ولا تستخدم `*`.

يشتق Compose متغير `FORWARDED_ALLOW_IPS` داخل خدمة `api` من
`GATEWAY_PEER_IP`؛ لا تدخله يدويًا. تستبدل Nginx قيم `X-Real-IP` و
`X-Forwarded-For` بعنوان النظير المباشر `$remote_addr` ولا تلحق السلسلة الواردة،
وتحذف ترويسة `Forwarded` الواردة، وتعيد بناء ترويسات Host من `$host`. تحفظ
`X-Forwarded-Proto` فقط عندما تكون قيمتها المطهرة المطابقة تمامًا `http` أو
`https`، وإلا تستخدم Scheme الذي رأته البوابة.

لذلك يجب إعداد Proxy الخارجي في Coolify ليمنع الوصول المباشر إلى الحاوية ويستبدل
ولا يمرر ترويسات `Forwarded` و`X-Forwarded-*` الواردة من العميل، خصوصًا
`X-Forwarded-Proto`. اختبر في Staging أيضًا بدء صورة Nginx القياسية مع Root
filesystem للقراءة فقط و`tmpfs` للمسارات `/var/cache/nginx` و`/var/run` و`/tmp`
ومجموعة القدرات المحدودة في Compose؛ لم يجر اختبار تشغيل لهذه القيود هنا.

## الأسرار التي ينشئها Coolify تلقائيًا

لا تُدخل القيم التالية يدويًا؛ مجرد وجودها داخل Compose يجعل Coolify ينشئها،
ثم يمرر كل سر فقط إلى الخدمات التي تحتاج دوره:

```text
SERVICE_PASSWORD_64_POSTGRES
SERVICE_PASSWORD_64_ADMIN
SERVICE_HEX_128_SESSION
SERVICE_PASSWORD_64_OPENCODE
SERVICE_PASSWORD_64_REDIS
```

الاستخدام الفعلي داخل الحاويات:

```text
POSTGRES_PASSWORD  ← SERVICE_PASSWORD_64_POSTGRES
ADMIN_PASSWORD     ← SERVICE_PASSWORD_64_ADMIN
SESSION_SECRET     ← SERVICE_HEX_128_SESSION
OPENCODE password  ← SERVICE_PASSWORD_64_OPENCODE
REDIS password     ← SERVICE_PASSWORD_64_REDIS
```

كما يبني Compose رابطَي قاعدة البيانات وRedis تلقائيًا، لذلك **لا تضف
`DATABASE_URL` أو `REDIS_URL` يدويًا**.

في Coolify لا تضف `OPENCODE_SERVER_PASSWORD` ولا كلمة مرور OpenCode محلية؛ يولد
Coolify `SERVICE_PASSWORD_64_OPENCODE` ويضعها Compose فقط في مفتاح
`OPENCODE_SERVER_PASSWORD` لدى `api` و`opencode-runtime` و`formatting-worker`.

## معرفة كلمة مرور المدير

بعد أن يحلل Coolify ملف Compose، افتح قائمة المتغيرات وابحث عن:

```text
SERVICE_PASSWORD_64_ADMIN
```

اسم المستخدم هو قيمة `ADMIN_USERNAME`، والقيمة التي أنشأها Coolify هي كلمة المرور.

## الدومين

اربط الدومين بخدمة:

```text
gateway
```

على المنفذ الداخلي:

```text
80
```

لا تربط دومينًا بخدمات `api` أو `postgres` أو `redis` أو العمال أو `opencode-runtime`.

## تنبيه الثبات

تظل القيم المولدة ثابتة داخل مورد Coolify نفسه. لا تغيّر أسماء متغيرات `SERVICE_*` بعد إنشاء قاعدة البيانات، ولا تحذف المورد وتعيد إنشاؤه مع Volume قديم إلا بعد حفظ القيم؛ وإلا قد تصبح كلمة مرور PostgreSQL الجديدة مختلفة عن كلمة المرور المخزنة في الـVolume.

## مرجع Coolify

- https://coolify.io/docs/knowledge-base/environment-variables
- https://coolify.io/docs/knowledge-base/docker/compose
