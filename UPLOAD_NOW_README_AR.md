# طريقة استخدام هذه الحزمة

## عند توفر مشروع التطبيق الأصلي لديك

1. فك هذه الحزمة.
2. طبّق ميزة التنسيق على مشروعك الأصلي:

```bash
python scripts/apply_formatting_integration.py \
  /path/to/youtube-deepgram-transcriber \
  --expected-tree-sha256 <trusted-canonical-tree-sha256>
```

التطبيق المباشر يرفض خط أساس بلا هوية افتراضيًا. استخدم بصمة شجرة من سجل مستقل
موثوق، أو استخدم `--acknowledge-unverified-base` فقط بعد قبول التحذير بأن الفحص
بنيوي لا يثبت الإصدار أو سلامة المحتوى. Builder مع ZIP المرجعي هو المسار الآمن.

3. إذا كان `docker-compose.formatting.yml` موجودًا عند أي عمق، لا تكمل. راجعه وانقل
   المطلوب يدويًا إلى Compose الموحد ثم احذفه أو انقله وأعد الدمج.
4. افحص مسار `.formatting-integration-backup-*` المطبوع وملف
   `integration-backup.json` الذي يجرد الملفات المنشأة والمستبدلة. إذا فشلت الاستعادة، استرد
   الملفات منه ولا تكمل. بعد نجاح الدمج أرشفه خارج جذر المشروع، وتأكد من إمكان
   قراءة الأرشيف، ثم يزيل المشغل نسخة Backup من شجرة المشروع يدويًا.
5. شغّل الفحص البنيوي (Verifier) على المجلد الناتج، وأوقف الرفع عند أي خطأ:

```bash
python scripts/verify_coolify_bundle.py /path/to/youtube-deepgram-transcriber
```

6. لا تعتبر نجاح الفحص إثبات بناء أو اكتمال انتقالي. شغّل خارجيًا
   `docker compose config` ثم بناء جميع الصور فعليًا، وأوقف الإصدار عند أي فشل.
7. ارفع **مجلد المشروع الناتج كاملًا** إلى GitHub أو إلى مصدر Coolify.
8. في Coolify اختر الملف:

```text
docker-compose.yml
```

9. أدخل القيم اليدوية الموضحة في `COOLIFY_ENVIRONMENT_VARIABLES_AR.md`.
10. اربط الدومين بخدمة `gateway` على المنفذ 80.
11. تحقق في Staging أن Coolify يدعم IPAM والعنوان `GATEWAY_PEER_IP` الثابت داخل
   `GATEWAY_NETWORK_SUBNET` من دون تعارض؛ هذه بوابة تشغيل إلزامية غير منفذة هنا.
12. تحقق أن Proxy في Coolify يطهر `X-Forwarded-Proto` وجميع ترويسات Forwarded، وأن Nginx يبدأ بقيود
    `read_only` و`tmpfs` والقدرات المحدودة؛ لا تضبط `FORWARDED_ALLOW_IPS` يدويًا.
13. نفّذ Deploy مع إعادة بناء الصور.

## بناء ZIP واحد من الأرشيف الأصلي

```bash
python scripts/build_full_source_from_original.py \
  /path/to/youtube-deepgram-transcriber.zip \
  /path/to/youtube-deepgram-transcriber-with-formatting.zip
```

يحتوي الأرشيف الناتج على `docker-compose.yml` الموحد وملفات Docker المطلوبة.
يجب أن يختلف مسارا المصدر والناتج دائمًا، ويجب ألا يكون الناتج موجودًا عند البدء؛
لا يوجد overwrite. اختر مسارًا جديدًا أو أزل القديم يدويًا قبل تشغيل Builder. يبني ZIP في حجر خاص، ثم يشغّل
Verifier وفحص سلامة ZIP، وينظف Backup الدمج وشجرة العمل قبل النشر. يمسك قفلًا حصريًا
بجانب الناتج طوال العملية ولا يحذف القفل القديم تلقائيًا. يُفتح المصدر مرة واحدة
ويُبصم ويُفك من المقبض نفسه مع فحص الهوية والتغير، ثم يعاد Hash الحجر فورًا قبل النشر
والملف النهائي بعده. تُثبت هوية/Hash شجرة التغليف، وتُبث الملفات من مقابض no-follow
ثابتة إلى ZIP بMetadata مضبوطة مع فحص قبل/بعد كل قراءة وإعادة فحص Snapshot كامل.
النشر no-clobber فقط، ولا توجد استعادة أو ملكية لناتج سابق.
`--allow-different-base` تجاوز يدوي غير آمن يتطلب معه أيضًا
`--acknowledge-unverified-base`، ولا يثبت مطابقة خط الأساس، ولا يجوز
وصف ناتجه بأنه Verified أو مصدر كامل حقيقي متحقق حتى عند نجاح الفحص البنيوي.

يفحص الدمج تداخل أسماء الحزم بين `backend/requirements.txt` و
`backend/requirements-formatting.txt` كنص محافظ. يسمح بالتكرار المكافئ تمامًا فقط؛
أما اختلاف القيود فيتطلب قيدًا موحدًا يدويًا قبل إعادة الدمج، ولا يُترك لمعاملة
تثبيت ثانية داخل Docker كي تستبدل القيد الأصلي بصمت.

## ما الذي لا يجب رفعه

لا ترفع:

```text
.env
.env.local وأي variant غير example/sample/template مقصود
auth.json
youtube_cookies.txt
أي ملف Cookies
.docker/config.json
.ssh
.git-credentials
kubeconfig
*.pem و*.key و*.p12 و*.pfx وملفات المفاتيح/الشهادات الأخرى
بيانات اعتماد AWS/Azure/GCloud
قواعد البيانات والكاش والحالة المحلية
الروابط الرمزية أو المكسورة أو الصلبة وReparse Points والملفات الخاصة
node_modules
.pytest_cache
.formatting-integration-backup-* عند أي عمق
docker-compose.formatting.yml عند أي عمق
```

يفشل Builder وVerifier إذا بقي أي عنصر في القائمة أو ملف مشتبه بأنه سر بدل حذفه
بصمت. راجع الملف وانقله يدويًا خارج المصدر، ثم أعد البناء أو التحقق.
