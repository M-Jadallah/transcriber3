# قائمة نشر نظام التنسيق على Coolify

## قبل الدمج

- خذ Backup من المستودع وقاعدة PostgreSQL.
- تأكد أن المشروع الحالي يبني بنجاح قبل الإضافة.
- ابدأ من `.env.coolify.manual.example` عند إدخال متغيرات Coolify اليدوية؛ لا تنسخ أسرار الأمثلة المحلية، واترك متغيرات `SERVICE_*` لـCoolify كي يولدها.
- اضبط `APP_URL` و`TRUSTED_HOSTS` ومفاتيح Deepgram الخمسة. ملف الإنتاج يثبت
  `COOKIE_SECURE=true` ولا ينشر Host port؛ التشغيل المحلي يحتاج Override منفصلًا.
- لا تضف `OPENCODE_SERVER_PASSWORD` في Coolify؛ يستخدم الإنتاج
  `SERVICE_PASSWORD_64_OPENCODE` المولد تلقائيًا. أي تشغيل محلي منفصل يحتاج سر
  OpenCode يدويًا مخصصًا لا ملف Compose الحالي كما هو.
- تحقق أن `GATEWAY_PEER_IP` داخل `GATEWAY_NETWORK_SUBNET` ولا يتعارض مع شبكة
  مضيف. اختبر في Staging أن إصدار Coolify يدعم IPAM والعنوان الساكن ويحافظ عليه؛
  لا يكتمل قبول النشر قبل هذه البوابة التشغيلية.
- لا تضبط `FORWARDED_ALLOW_IPS` يدويًا؛ يشتقه Compose من `GATEWAY_PEER_IP`.
  تحقق أن Proxy في Coolify يستبدل ترويسات `Forwarded` و`X-Forwarded-*` غير
  الموثوقة ولا يمرر إلا Scheme واحدة مطابقة تمامًا لـ`http` أو `https`، وأنه لا
  يمكن تجاوز Proxy والوصول مباشرة إلى `gateway`.
- تحقق في Staging أن Nginx القياسي يبدأ مع Root filesystem للقراءة فقط، و`tmpfs`
  للمسارات `/var/cache/nginx` و`/var/run` و`/tmp`، والقدرات المحدودة في Compose.
  هذه بوابة تشغيل لأن توافق الصورة لم يُنفذ هنا.

## الدمج

- إذا وجد `docker-compose.formatting.yml` قديمًا عند أي عمق، راجعه وانقل المطلوب إلى الملف
  الموحد ثم انقله أو احذفه يدويًا قبل إعادة الدمج. لا يُحذف تلقائيًا.

```bash
python scripts/apply_formatting_integration.py \
  /path/to/project \
  --expected-tree-sha256 <trusted-canonical-tree-sha256>
```

لا يعمل وضع المجلد بلا إقرار هوية. استخدم بصمة موثوقة مستقلة، أو
`--acknowledge-unverified-base` فقط بعد قبول أن الفحص بنيوي وغير مثبت للنسخة.
يفحص السكربت كل الأسلاف والشجرة ويرفض الروابط، ومنها الصلبة، وReparse Points والملفات الخاصة.

راجع الرسائل ومجلد `.formatting-integration-backup-*` وملف جرد الاسترداد
`integration-backup.json`. إذا أبلغ السكربت عن فشل
استعادة، استخدم نسخه لاسترداد الملفات ولا تكمل. بعد نجاح الدمج أرشف المجلد كاملًا
خارج جذر المشروع وتأكد من إمكان قراءته، ثم أزله يدويًا من الشجرة. بعدها فقط شغّل
الفحص البنيوي الإلزامي (Verifier) قبل الرفع أو Alembic أو Deploy:

```bash
python scripts/verify_coolify_bundle.py /path/to/project
```

يرفض Verifier أي Backup أو overlay قديم عند أي عمق، إضافة إلى الأسرار والاعتمادات
والمفاتيح وCookies وقواعد البيانات والكاش والحالة المحلية والملفات الخاصة. ويتطلب
`frontend/index.html` و`package.json` وLockfile مدعومًا واحدًا على الأقل. نجاحه
بنيوي فقط ولا يثبت الاكتمال الانتقالي للمصدر أو نجاح Compose أو البناء. أسماء إعدادات
Vite/TypeScript الأصلية غير معروفة في هذه الحزمة، فلا تُخمن. أي خطأ يمنع المتابعة.
كما يفرض مجموعة مفاتيح Compose العلوية الحالية حرفيًا ويرفض `include` و`extends`
ومفتاح الدمج العلوي وأي قسم غير متوقع، بما فيه `configs` و`secrets`. وعلى مستوى كل
خدمة يرفض `post_start` و`pre_stop` و`configs` و`secrets` و`extends`، ويرفض كليًا
`profiles` و`scale` و`deploy` لأن العقد الحالي يشغّل الخدمات الست عشرة افتراضيًا
بنسخة واحدة لكل خدمة ولا يحتوي استثناءات تحجيم أو تعطيل.
بعد نجاحه نفّذ:

```bash
cd /path/to/project
pytest -q
alembic -c backend/alembic.ini upgrade head
```

## البناء في بيئة Staging المجهزة بالقيم المطلوبة

```bash
docker compose -f docker-compose.yml config

docker compose -f docker-compose.yml build --pull

docker compose -f docker-compose.yml up -d
```

يجب أن تنجح بوابة `config` وبناء كل الصور فعليًا خارج Verifier. وفي Coolify يجب
اختبار تطهير `X-Forwarded-Proto` وبقية ترويسات Forwarded قبل قبول الإصدار.

## الصحة

```bash
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs opencode-runtime
docker compose -f docker-compose.yml logs formatting-worker
docker compose -f docker-compose.yml logs formatting-dispatcher
```

يجب أن تكون `opencode-runtime` و`formatting-worker` و`formatting-dispatcher` في حالة Healthy.
يتضمن ملف Compose الموحّد 16 خدمة، منها خدمتا التهيئة وDispatcher مستقل للتسليم.
صحة Dispatcher وظيفية وتقيس حداثة Heartbeat ذري بعد دورة ناجحة. صحة Scheduler
عملية فقط: تتحقق من وجود ابن Tini الوحيد الذي يشغل `app.scheduler` ولا تثبت تنفيذ
المهام الدورية.

## اختبار وظيفي

- تسجيل الدخول إلى التطبيق.
- فتح الإعدادات وربط ChatGPT Plus/Pro.
- فتح صفحة المهارات ورفع ZIP صحيح.
- اختيار المهارة الافتراضية والنموذج.
- تشغيل تفريغ قصير ثم الضغط على التنسيق.
- فتح النتيجة وتنزيل Word أو الملفات التي تنتجها المهارة.
- إعادة التنسيق والتأكد أن المحاولة السابقة بقيت موجودة.
- فصل الحساب وإعادة الربط.
