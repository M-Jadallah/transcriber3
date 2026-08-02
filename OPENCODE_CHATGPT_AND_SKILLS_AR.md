# دليل ربط ChatGPT بـ OpenCode وإدارة مهارات التنسيق

هذا الدليل خاص بميزة التنسيق الاختيارية المضافة إلى تطبيق التفريغ. لا تغيّر الميزة نص Deepgram الأصلي؛ كل تشغيل ينشئ مهمة ومنتجًا جديدًا مرتبطًا بالتفريغ الأصلي.

## 1. مكونات الميزة

```text
صفحة التفريغات
    └── زر «تنسيق بالذكاء الاصطناعي»
             ↓
FastAPI: إنشاء Formatting Job وحفظ Snapshot
             ↓
Redis / Celery queue: formatting
             ↓
Formatting Worker
             ↓  opencode run --attach
OpenCode Runtime الداخلي
             ↓
ChatGPT Plus/Pro أو مزود آخر
             ↓
/data/formatting-execution/<job-id>-g<generation>/output/
             ↓  فحص ونسخ ثابت
/data/formatting/jobs/<job-id>/executions/<job-id>-g<generation>/output/
```

توجد ثلاثة مسارات دائمة منفصلة:

```text
formatting-data       → أرشيفات المهارات وإصداراتها المستخرجة
formatting-jobs-data  → Snapshots الإدخال ونتائج الأجيال الدائمة تحت jobs/<job-id>/executions/
opencode-data         → بيانات مصادقة المزود فقط
```

لا تُحفظ كلمة مرور ChatGPT أو البريد الإلكتروني في PostgreSQL، ولا تُعرض رموز OAuth في واجهة الموقع.

---

## 2. متطلبات النشر

في Coolify اضبط اسم المستخدم فقط:

```env
OPENCODE_SERVER_USERNAME=opencode
```

ينشئ Coolify `SERVICE_PASSWORD_64_OPENCODE` تلقائيًا، ويحوّله Compose إلى
`OPENCODE_SERVER_PASSWORD` فقط داخل `api` و`opencode-runtime`
و`formatting-worker`. لا تدخل `OPENCODE_SERVER_PASSWORD` يدويًا في Coolify.

إعدادات اختيارية:

```env
OPENCODE_VERSION=1.18.8
FORMATTING_DEFAULT_MODEL=openai/gpt-5.6-sol
FORMATTING_DEFAULT_REASONING=high
FORMATTING_TIMEOUT_SECONDS=7200
FORMATTING_INPUT_MAX_BYTES=20971520
FORMATTING_STORAGE_MAX_BYTES=21474836480
FORMATTING_EXECUTION_WORKSPACE_MAX_ENTRIES=5000
FORMATTING_EXECUTION_WORKSPACE_MAX_BYTES=805306368
FORMATTING_SKILL_MAX_ARCHIVE_BYTES=52428800
FORMATTING_SKILL_MAX_FILES=2000
FORMATTING_SKILL_MAX_UNPACKED_BYTES=268435456
FORMATTING_OUTPUT_MAX_FILES=100
FORMATTING_OUTPUT_MAX_TOTAL_BYTES=209715200
FORMATTING_OUTPUT_MAX_SINGLE_FILE_BYTES=104857600
```

لا تضع كلمة مرور OpenCode أو أي ملف مصادقة في GitHub.

### التشغيل المحلي

ملف Compose الحالي عقد إنتاج لـCoolify وليس Stack محليًا مدعومًا كما هو. فهو
يتطلب `APP_URL` و`TRUSTED_HOSTS` ومفاتيح Deepgram والأسرار المولدة، ويثبت Cookies
الآمنة، ولا ينشر Host port. يحتاج التشغيل المحلي Override منفصلًا يضيف Ingress
محليًا ويستخدم سرًا يدويًا مخصصًا مثل `OPENCODE_LOCAL_PASSWORD` ثم يمرره باسم
`OPENCODE_SERVER_PASSWORD` إلى الأدوار الثلاثة نفسها. لا تستخدم
`SERVICE_PASSWORD_64_OPENCODE` كإرشاد لكلمة مرور محلية، ولا تُدخل السر في Git.

### Coolify

اختر `docker-compose.yml` الموحد في Coolify. لا تربط Domain بخدمة
`opencode-runtime` ولا بخدمة `formatting-worker`؛ الخدمة العامة الوحيدة تبقى
الـGateway الحالي.

---

## 3. ربط حساب ChatGPT من صفحة الإعدادات

بعد نجاح النشر:

1. سجّل دخولك إلى تطبيق التفريغ بحساب المدير.
2. افتح **الإعدادات**.
3. انتقل إلى قسم **التنسيق بالذكاء الاصطناعي**.
4. تحقق أن بطاقة OpenCode تعرض **متاح**.
5. اختر المزود `openai`.
6. اختر طريقة **ChatGPT Plus/Pro** التي يعرضها OpenCode.
7. اضغط **بدء ربط الحساب**.
8. ستفتح نافذة المصادقة الرسمية في تبويب جديد.
9. سجّل الدخول بحساب ChatGPT المطلوب ووافق على الربط.
10. عد إلى الإعدادات واضغط **تحديث الحالة**.
11. عند النجاح تظهر حالة **متصل** وتظهر نماذج المزود في حقل اختيار النموذج.
12. لفصل الحساب لاحقًا اضغط **فصل الحساب**؛ يحذف النظام ملف الاعتماد من الـVolume ويعيد تشغيل خدمة OpenCode الداخلية تلقائيًا.

### طريقتا OAuth اللتان قد يعيدهما OpenCode

واجهة التطبيق لا تفترض ترتيبًا ثابتًا؛ فهي تقرأ طرق المصادقة مباشرة من OpenCode.

- `auto`: يفتح المتصفح ويُكمل OpenCode رد النداء تلقائيًا.
- `code`: بعد تسجيل الدخول تحصل على رمز، وتلصقه في الحقل داخل صفحة الإعدادات ثم تضغط **إكمال الربط**.

على VPS بعيد، طريقة `code` هي الأكثر وضوحًا إن كانت متاحة. إذا عرض OpenCode طريقة `auto` فقط وكان رد النداء موجّهًا إلى loopback لا يستطيع متصفحك الوصول إليه، استخدم طريقة headless/code التي يعرضها إصدار OpenCode، أو نفّذ تسجيل الدخول مرة واحدة من Terminal الخدمة مع بقاء Volume نفسه. الواجهة ستتعرف على الجلسة فورًا لأن بيانات المصادقة مشتركة مع `opencode-runtime`.

### التحقق من داخل السيرفر عند الحاجة

افتح Terminal خدمة `opencode-runtime` وشغّل:

```bash
opencode auth list
opencode models openai
```

لا تنسخ ناتج ملفات الاعتماد ولا تعرضه في سجلات عامة.

### موضع بيانات المصادقة

الحزمة تجعل OpenCode يستخدم:

```text
XDG_DATA_HOME=/data/opencode/data
XDG_CONFIG_HOME=/tmp/opencode-config
XDG_CACHE_HOME=/tmp/opencode-cache
```

يرتبط `/data/opencode/data` وحده بـVolume دائم اسمه `opencode-data` لحفظ بيانات المصادقة فقط، بينما تقع الإعدادات والكاش تحت `/tmp` المركب كـ`tmpfs`. لا يحتاج تطبيق الويب إلى قراءة ملف الاعتماد؛ يتواصل فقط مع واجهة OpenCode الداخلية المحمية بـBasic Auth. كما توجد خدمة تحكم داخلية على المنفذ `4097` لتنفيذ فصل الحساب فقط؛ هذا المنفذ لا يُنشر للعامة.

---

## 4. اختيار النموذج ومستوى التفكير

داخل قسم الإعدادات:

- **النموذج:** اختر من القائمة التي يعيدها OpenCode، أو اكتب معرّفًا كاملًا بصيغة `provider/model`.
- **مستوى التفكير:** `low` أو `medium` أو `high` أو `xhigh`.
- **المهارة الافتراضية:** إحدى المهارات المفعلة من صفحة المهارات.

عند الضغط على زر التنسيق، يحفظ النظام Snapshot من:

```text
skill_id
skill_name
skill_sha256
model
reasoning
input_sha256
```

لذلك تغيير الإعدادات بعد بدء المهمة لا يغيّرها. إعادة التنسيق تنشئ محاولة جديدة ولا تستبدل النتيجة السابقة.

يفضل اختيار النموذج من القائمة الفعلية بعد ربط الحساب بدل الاعتماد على قيمة افتراضية قد لا تكون متاحة في حسابك أو إصدار OpenCode الحالي.

---

## 5. صفحة إدارة المهارات

افتح **مهارات التنسيق** من القائمة الجانبية، ثم اضغط **رفع مهارة ZIP**.

يقوم النظام تلقائيًا بالآتي قبل اعتمادها:

- التحقق من أن الملف ZIP صالح.
- رفض المسارات المطلقة و`..` وZip Slip.
- رفض الروابط الرمزية.
- تحديد الحجم، وعدد الملفات، والحجم الإجمالي بعد الفك.
- اشتراط وجود `SKILL.md` واحد فقط.
- قراءة YAML front matter.
- التحقق من `name` و`description`، ومن أن اسم المجلد الخارجي يطابق `name` عند استخدام مجلد واحد داخل ZIP.
- التحقق من أن حقول `license` و`compatibility` نصوص، وأن `metadata`—إن وجدت—خريطة نص إلى نص.
- حساب SHA-256 للأرشيف.
- حفظ كل إصدار بصورة مستقلة.
- استخراج الملفات ذرّيًا.
- تسجيل الإصدار في PostgreSQL.
- اختيار أول مهارة مرفوعة كافتراضية إن لم توجد مهارة افتراضية.

### الشكل الصحيح للـZIP

يمكن أن يكون `SKILL.md` في الجذر:

```text
my-skill.zip
├── SKILL.md
├── scripts/
├── references/
└── templates/
```

أو داخل مجلد واحد:

```text
my-skill.zip
└── my-skill/
    ├── SKILL.md
    ├── scripts/
    └── templates/
```

مثال صحيح لملف `SKILL.md`:

```md
---
name: arabic-lesson-formatter
description: Format Arabic lesson transcripts into a structured, reviewed document.
---

# Workflow

1. Read the supplied transcript.
2. Preserve meaning and evidence.
3. Write the formatted output to the output directory.
```

قواعد الاسم:

- من حرف واحد إلى 64 حرفًا.
- أحرف إنجليزية صغيرة وأرقام عند الحاجة.
- شرطة `-` بين الكلمات.
- بلا مسافات أو شرطات متتالية.
- عند وضع المهارة داخل مجلد واحد، يجب أن يكون اسم المجلد مطابقًا تمامًا لقيمة `name`.

### مكان الحفظ داخل الحاويات

```text
/data/formatting/skills/archives/<sha256>.zip
/data/formatting/skills/versions/<sha256>/<skill-name>/SKILL.md
```

وعند تشغيل مهمة تُستخرج النسخة المختارة بعد التحقق منها إلى مساحة الجيل في
Volume التبادل فقط:

```text
/data/formatting-execution/<job-id>-g<generation>/.opencode/skills/<skill-name>/SKILL.md
```

لا توجد النسخة المختارة في `formatting-jobs-data` أو `opencode-data`. يبقى
الأرشيف الموثق في `formatting-data`، أما مادّة التنفيذ المختارة فتوجد فقط داخل
مساحة الجيل في `formatting-execution-exchange`.

وبذلك لا تتأثر مهمة قديمة إذا رفعت إصدارًا جديدًا من المهارة لاحقًا.

### التعطيل بدل الحذف النهائي

زر **تعطيل** يمنع استخدام المهارة في مهام جديدة، لكنه لا يحذف أرشيفها ولا يكسر المهام السابقة. يمكن إعادة تفعيلها من الصفحة نفسها.

---

## 6. الأدوات والاعتماديات التي تستخدمها المهارة

رفع ZIP لا يثبت حزم نظام عشوائية تلقائيًا؛ هذا قرار أمني مقصود. في السياسة
المشددة الحالية تُتاح للمهارة تعليماتها وملفاتها المرجعية وأدوات القراءة والتحرير
المحددة فقط. أداة Bash العامة معطلة، لذلك لا تدّعي هذه البنية أن المهارة تستطيع
تشغيل Python أو Node.js أو أوامر الصورة مباشرة. وجود مجلد `scripts/` داخل ZIP
لا يجعله قابلًا للتنفيذ؛ هو مادة يقرأها الوكيل فقط في هذا التصميم.

`backend/requirements-formatting.txt` و`backend/Dockerfile.formatting` يضبطان
اعتماديات كود التطبيق المراجع وصورته، ولا يمنح مجرد إضافة حزمة فيهما المهارة
قدرة تنفيذ أوامر. أي توسيع مستقبلي لتشغيل برامج من المهارة يحتاج تصميم صلاحية
ضيقة ومراجعة أمنية مستقلة؛ لا تسمح لملف ZIP بتثبيت حزم أو تشغيل مثبتات.

---

## 7. عقد الإدخال والإخراج

لكل مهمة:

```text
/data/formatting-execution/<job-id>-g<generation>/
├── input/
│   └── transcript.txt       # Snapshot لا يُعدّل
├── .opencode/
│   └── skills/<name>/...
├── opencode.json
└── output/
    ├── result.md            # إلزامي
    ├── manifest.json        # مطلوب في الـPrompt
    └── أي ملفات إضافية
```

بعد الفحص تنسخ النتائج والسجلات إلى
`/data/formatting/jobs/<job-id>/executions/<job-id>-g<generation>/`، ولا تستخدم
الحزمة مسار نتيجة دائمًا غير مرتبط بالجيل.

الامتدادات التي يسجلها التطبيق:

```text
.md  .txt  .docx  .json  .html  .pdf
```

لا تعتمد حالة النجاح على رسالة الوكيل فقط. قبل تعليم المهمة كمكتملة، يقوم العامل بما يلي:

- إعادة حساب بصمة Snapshot الإدخال وبصمة أرشيف المهارة ومقارنتها بالقيم المحفوظة.
- اشتراط وجود `output/result.md`.
- رفض الروابط الرمزية وأسماء الملفات غير الآمنة.
- تطبيق حدود عدد الملفات والحجم الإجمالي وحجم الملف الواحد.
- فتح JSON وتحليله.
- فحص ترويسة PDF.
- فحص بنية DOCX كأرشيف Office ثم فتحه فعليًا بواسطة `python-docx`.

الحدود الافتراضية للمخرجات هي 100 ملف، و200 MB إجماليًا، و100 MB للملف الواحد. وتراقب مساحة التنفيذ الحية كاملة بحد افتراضي 5000 عنصر و768 MB يشمل النص والمهارة والمخرجات والسجلات. يمكن تغييرها بمتغيرات البيئة المذكورة أعلاه.

---

## 8. استكشاف الأخطاء

### OpenCode غير متاح

تحقق من:

```bash
docker compose -f docker-compose.yml logs opencode-runtime
```

وتأكد في Coolify أن `SERVICE_PASSWORD_64_OPENCODE` مولد، وأن Compose يمرره باسم
`OPENCODE_SERVER_PASSWORD` إلى `api` و`opencode-runtime` و`formatting-worker`
فقط؛ لا تنسخ قيمته إلى متغير يدوي آخر.

### الحساب لا يظهر متصلًا

1. اضغط تحديث الحالة.
2. افتح Terminal خدمة OpenCode وشغّل `opencode auth list`.
3. تأكد أن Volume `opencode-data` لم يُحذف عند Redeploy.
4. تأكد أن خدمة التحكم الداخلية على المنفذ `4097` سليمة؛ زر الفصل يعتمد عليها فقط.
5. أعد المصادقة من صفحة الإعدادات.

### النموذج غير موجود

اختر معرّفًا من القائمة بعد الربط. ويمكن التحقق من Terminal:

```bash
opencode models openai --refresh
```

### المهارة مرفوضة

تحقق من:

- ZIP صالح.
- `SKILL.md` واحد فقط.
- UTF-8.
- Front matter صحيح.
- اسم مطابق للقواعد.
- لا توجد روابط رمزية أو مسارات `../`.
- إذا كان ZIP يحتوي مجلدًا خارجيًا واحدًا، فاسمه مطابق لقيمة `name`.
- لا تتجاوز حدود الحجم وعدد الملفات المعرفة في متغيرات البيئة.

### المهمة فشلت دون ملفات

راجع:

```bash
docker compose -f docker-compose.yml logs formatting-worker
```

ثم تحقق أن تعليمات المهارة متوافقة مع الأدوات المسموحة وتنتج `output/result.md`.

---

## 9. ملاحظات أمنية وتشغيلية

- أبقِ التزامن `1` عند استخدام حساب ChatGPT شخصي.
- لا تكشف منفذي OpenCode الداخليين `4096` و`4097` للإنترنت.
- لا تركب Docker Socket داخل أي خدمة.
- لا تمنح `api` وصولًا إلى Volume اعتماد OpenCode.
- لا تضع أسرار التطبيق في مساحة عمل المهمة.
- ارفع مهارات تثق بمصدرها فقط. فحص ZIP يمنع أخطار الأرشيف المعروفة، لكنه لا يثبت أن تعليمات المهارة أو سكربتاتها سليمة منطقيًا.
- احتفظ بنسخة احتياطية مشفرة من `opencode-data` فقط عند الحاجة؛ تعامل معها ككلمة مرور.
- انسخ `formatting-data` إذا أردت الاحتفاظ بإصدارات المهارات، و`formatting-jobs-data` إذا أردت الاحتفاظ بنتائج التنسيق وسجل ملفاتها.
- إلغاء العامل ينهي عميل OpenCode المحلي، لكن إجهاض الجلسة البعيدة نفسها غير مثبت ولا توجد آلية موثقة له هنا.
- قد يترك الانهيار القاسي أثناء تبديل مجلد نتائج أو سجلات بقايا `.previous` أو `.copying`؛ لا تنفذ الحزمة مصالحة تلقائية لهذا السيناريو.
- هذه البنية مناسبة لأداة شخصية خاصة. عند تحويلها إلى خدمة متعددة المستخدمين أو تجارية، استخدم مزود API مخصصًا وسياسة تكلفة وحدود استخدام مستقلة.


## 10. إنشاء ZIP مصدر كامل من الأرشيف الأصلي

لأن حزمة الدمج تُوزع منفصلة عن الأرشيف الأصلي، يوجد سكربت يبني شجرة مصدر كاملة حقيقية:

```bash
python scripts/build_full_source_from_original.py \
  /path/to/youtube-deepgram-transcriber.zip \
  /path/to/youtube-deepgram-transcriber-with-formatting.zip
```

يتحقق السكربت افتراضيًا من بصمة آخر أرشيف مرجعي معروف، ويرفض تطابق مساري المصدر
والناتج، ويرفض أي ناتج موجود؛ اختر مسارًا جديدًا أو أزل القديم يدويًا قبل البدء.
لا يوجد خيار overwrite. يفكّه بأمان، ويرفض عناصر
الشجرة المحظورة والروابط وReparse Points والملفات الخاصة، ثم يطبق الدمج مع Backup
خارج المشروع. يمسك قفل إخراج حصريًا، ويبصم المصدر ويفكّه من المقبض الثابت نفسه،
ثم يبني ZIP في حجر خاص ويكمل Verifier والتنظيف. يعيد Hash الحجر قبل النشر والملف
النهائي بعده. يثبت Snapshot الشجرة وهوية/Hash كل ملف، ويبث Bytes من مقابض no-follow
إلى ZIP بMetadata مضبوطة مع فحص قبل/بعد القراءة. النشر no-clobber فقط، ولا توجد
استعادة لناتج سابق. كما يرفض اختلاف قيد
حزمة موجودة في ملفي requirements ويطلب قيدًا موحدًا يدويًا. يرفض
متغيرات `.env` غير الأمثلة المقصودة،
أو بيانات Docker/SSH/Kubernetes/Cloud، أو المفاتيح والشهادات، أو قواعد البيانات
والكاش والحالة المحلية، أو `auth.json` وCookies و`node_modules`. ويفشل إذا بقي
ملف مشتبه بأنه سر بدل حذفه بصمت.

`--allow-different-base` تجاوز يدوي غير آمن يتطلب أيضًا
`--acknowledge-unverified-base`. يبقى الفحص التمهيدي وVerifier
إلزاميين، لكن الناتج لا يكون متحققًا من مطابقة خط الأساس ولا يجوز وصفه بأنه
Verified أو مصدر كامل حقيقي متحقق.

قبل رفع المشروع المدمج أو نشره شغّل:

```bash
python scripts/verify_coolify_bundle.py /path/to/merged-project
```

---

## 11. مراجع المصادقة الحالية

OpenCode يدعم من قائمة OpenAI اختيار **ChatGPT Plus/Pro** وفتح تدفق المتصفح، كما يتيح مفتاح API. بيانات المصادقة تُخزن في مساحة بيانات OpenCode داخل `auth.json`، ولذلك رُبط `/data/opencode/data` وحده بVolume دائم ولم يُضمّن داخل ZIP؛ الإعدادات والكاش مؤقتان.

هذه الميزة تستخدم **OpenCode** كوسيط تشغيل، وليست Codex CLI الرسمي نفسه. OpenAI توثّق أن Codex الرسمي يدعم تسجيل الدخول بحساب ChatGPT أو بمفتاح API، وتوصي بمفتاح API للأتمتة العامة غير التفاعلية. أبقِ هذه البنية خاصة وعلى بنية موثوقة عند استخدام حساب ChatGPT الشخصي.

المراجع:

- https://opencode.ai/docs/providers/#openai
- https://opencode.ai/docs/troubleshooting/#storage
- https://developers.openai.com/codex/auth
- https://developers.openai.com/codex/auth/ci-cd-auth
