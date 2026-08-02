# بيان ملفات حزمة الدمج

> **NON-AUTHORITATIVE / غير معتمد:** هذا البيان قائمة تحريرية تاريخية، وليس جردًا
> مولدًا من الشجرة الحالية. لا تستخدمه لإثبات الاكتمال أو النزاهة قبل إعادة توليده
> من الناتج النهائي مع Manifest بصمات جديد.
>
> تحديث 2026-08-02: عدلت الدفعة الساكنة الحالية `frontend/Dockerfile` لإحكام
> ترويسات Nginx، وCMD الافتراضي في `backend/Dockerfile`، و`docker-compose.yml`
> لإعداد الثقة/حاوية البوابة، و`.dockerignore`، وVerifier واختباره الساكن، وأمثلة
> البيئة ووثائق النشر/الحالة/البيان. لم تُعد توليد `SHA256SUMS.txt`، ولم تُشغّل أو
> تُحلل أو تُستورد أو تُصرّف أو تُختبر أوامر Python أو المشروع أو Docker أو YAML،
> كما شملت تعديلات لاحقة ساكنة سكربتات الدمج/البناء/التحقق واختباراتها النصية.
> لم تُعدّل قيم checksums. هذا البيان نفسه stale وغير شامل، ولا يمثل مسحًا آليًا
> للشجرة أو دليل اكتمال.
>
> إضافة ساكنة لاحقة في 2026-08-02 عدلت Runtime وAPI ومهام التنسيق واختبارات
> المصدر الساكنة وأمثلة البيئة ووثائق المعمارية والحالة. أضيف عقد مخرجات ناجح،
> وقبول تخزين للمهارات والمهام، ومصالحة نشر دائمة بعد الانقطاع. لم تشمل الإضافة
> Compose أو verifier/integration/build أو Dockerfiles أو Frontend أو migration أو
> قيم checksums، ولم يُشغّل أو يُحلل أو يُستورد أو يُصرّف أو يُختبر أي أمر مشروع.
>
> إضافة ساكنة لاحقة أحكمت فقط سكربتات الدمج/البناء وقواعد الشجرة المشتركة،
> واختبارات النص والوثائق والحالة/البيان: فحص `lstat` وReparse/الملفات الخاصة
> والاحتواء، إقرار هوية خط الأساس، Metadata لجرد الاسترداد، وترتيب النشر/البصمة/
> التنظيف مع حجر الناتج عند الفشل. لم تُعدّل Backend أو Compose أو Verifier أو
> Docker أو Frontend أو checksums، ولم يُشغّل أو يُستورد أو يُحلل أو يُصرّف أو
> يُختبر أو يُحسب SHA لأي ملف في هذه الدفعة.
>
> تحديث ساكن لاحق في 2026-08-02 أحكم مصفوفة build/image البنيوية، ومدخلات بناء
> الواجهة الأساسية من دون تخمين أسماء Vite/TypeScript الأصلية، وعقد `/api/` في
> Nginx، وحماية gateway، وسياسة الكاش/الملفات الخاصة، وأضاف mount مساحة التنفيذ
> وحدها إلى Dispatcher لأعمال Janitor بلا اعتماد OpenCode. عُدلت Compose وDockerfile
> و`.dockerignore` وVerifier وسياسة الشجرة واختبارها الساكن ووثائق الحالة والنشر،
> وحُذفت مخلفات `.pytest_cache` و`__pycache__`. لم تُشغّل أو تُحلل أو تُستورد أو
> تُصرّف أو تُختبر Python أو Docker أو YAML أو أوامر المشروع، ولم تتغير checksums.
>
> إضافة ساكنة أخرى في 2026-08-02 عدلت Runtime ومهام/Repository/Dispatcher التنسيق
> لتثبيت جرد مدخلات تنفيذ غير قابل للتغيير والتحقق منه بعد OpenCode، وإضافة Janitor
> مؤقت واعٍ بالـDB والجيل والـLease. عُدلت إعدادات Compose وأمثلة البيئة والاختبارات
> الساكنة ووثائق المعمارية/الحالة/البيان فقط ضمن هذا النطاق؛ لم تُضف migration ولم
> تُعدل integration/verifier أو Frontend أو `SHA256SUMS.txt`. لم يُنفذ أو يُستورد
> أو يُحلل أو يُصرّف أو يُختبر أي كود أو أمر مشروع، وتبقى checksums قديمة.
>
> تحديث ساكن لاحق في 2026-08-02 عدل فقط Verifier واختباره الساكن و`.dockerignore`
> والوثائق والحالة وهذا البيان. أضيفت مصفوفة رفض تجاوزات Runtime لكل الخدمات،
> والتحقق من المستخدم/التقوية/mounts، واشتراط تعريفات volumes علوية فارغة/null،
> واختبارات mutation ومخلفات cache. لم توجد مخلفات `.pytest_cache` أو
> `__pycache__` أو `.pyc` أو `.pyo` للحذف عند الفحص الساكن. لم تُعدل Compose أو
> Backend أو integration أو Frontend أو checksums، ولم يُشغّل أو يُستورد أو يُحلل
> أو يُصرّف أو يُختبر أي كود أو Python أو Docker أو YAML، ولم تُعد بصمات SHA.
>
> تحديث ساكن لاحق في 2026-08-02 اقتصر على سكربتي الدمج والبناء، واختبارات النص،
> والوثائق/الحالة/البيان. أصبح Builder يرفض تطابق المصدر والناتج، ويرفض الاستبدال
> بلا خيار صريح، ويبني ويفحص ويبصم في حجر قبل تنظيف الاسترداد والعمل
> وآخر `os.replace` ذري، مع استعادة الناتج القديم وتنظيف `BaseException`. كما أصبح
> تداخل requirements يقبل التكرار النصي المكافئ فقط ويرفض اختلاف القيود طالبًا دمجًا
> يدويًا. لم تُعدل Backend أو Compose أو Verifier أو Dockerfiles أو Frontend أو
> checksums، ولم يُشغّل أو يُستورد أو يُحلل أو يُصرّف أو يُختبر أو يُحسب SHA.
>
> تحديث ساكن لاحق في 2026-08-02 اقتصر على Builder، وملف
> `backend/requirements-formatting.txt`، واختبارات النص ووثائق التشغيل/الحالة/هذا
> البيان. ربط Builder Hash وفك ZIP المصدر بمقبض وهوية ثابتين، وأضاف قفل إخراج حصريًا،
> وإعادة Hash قبل/بعد النشر، ونشر no-clobber. كانت تلك الدفعة تتضمن مسار استبدال
> واستعادة ألغي بالكامل في التحديث الأحدث. طوبقت قيود الاعتماديات الأربعة المكررة نصيًا مع الملف الأساسي، مع
> إبقاء اختلاف أي قيد هدف سببًا للفشل وطلب الدمج اليدوي. لم تُعدل أي ملفات Backend
> أخرى أو Compose أو Verifier أو Docker أو Frontend أو checksums، ولم يُشغّل أو
> يُستورد أو يُحلل أو يُصرّف أو يُختبر أو يُحسب SHA أو يُجدد Manifest بصمات.
>
> تحديث ساكن لاحق في 2026-08-02 اقتصر على Verifier واختبار mutation الساكن
> ووثائق النشر/التحقق والحالة/البيان وحذف كاش مولد. أصبح عقد مفاتيح Compose
> العلوية دقيقًا ويرفض الدمج/التركيب الخارجي و`configs` و`secrets`، وتمنع كل خدمة
> lifecycle/config/secret overrides و`profiles` و`scale` و`deploy` لضمان تفعيل
> الخدمات المطلوبة افتراضيًا بنسخة واحدة. حُذفت محتويات `.pytest_cache` ومجلد
> `tests/__pycache__` الفارغ، ولم توجد ملفات `.pyc` أو `.pyo`. لم تُعدل Compose أو
> Backend أو integration/build أو Dockerfiles أو Frontend أو checksums، ولم يُشغّل
> أو يُستورد أو يُحلل أو يُصرّف أو يُختبر أي كود أو Python أو Docker أو YAML، ولم
> تُحسب أو تُجدّد بصمات.
>
> تحديث ساكن لاحق في 2026-08-02 اقتصر على سكربتي الدمج والبناء، واختبارات النص،
> ووثائق التشغيل/الحالة/هذا البيان. أضيف قفل مشروع حصري `O_CREAT|O_EXCL` يغطي
> الفحص النهائي لهوية الشجرة والأهداف وBackup والالتزام وrollback، مع رفض القفل
> القديم دون حذفه، وتسجيل كل وجهة محاولة قبل الاستبدال وrollback واعٍ بملكية
> هوية/Hash الناتج. أصبح التغليف يبث Snapshot متحققًا من مقابض no-follow إلى
> `ZipInfo` مضبوط مع فحص الهوية/Hash قبل/بعد القراءة. حُذف overwrite للناتج وخياره
> نهائيًا؛ الناتج يجب أن يكون غائبًا والنشر no-clobber فقط. لم تُعدل Backend أو
> Compose أو Verifier أو Docker أو Frontend أو checksums، ولم يُشغّل أو يُستورد أو
> يُحلل أو يُصرّف أو يُختبر أو يُحسب SHA لأي ملف.

## Backend

- `backend/Dockerfile`
- `backend/Dockerfile.formatting`
- `backend/alembic/versions/20260801_0100_add_formatting_subsystem.py`
- `backend/app/api/formatting.py`
- `backend/app/formatting/__init__.py`
- `backend/app/formatting/celery_bootstrap.py`
- `backend/app/formatting/config.py`
- `backend/app/formatting/opencode_client.py`
- `backend/app/formatting/opencode_control.py`
- `backend/app/formatting/outbox_dispatcher.py`
- `backend/app/formatting/repository.py`
- `backend/app/formatting/runtime.py`
- `backend/app/formatting/skills.py`
- `backend/app/formatting/tasks.py`
- `backend/requirements-formatting.txt`

## Frontend

- `frontend/Dockerfile`
- `frontend/src/components/FormatTranscriptButton.tsx`
- `frontend/src/components/FormattingNavigationLink.tsx`
- `frontend/src/components/FormattingSettingsPanel.tsx`
- `frontend/src/formatting.ts`
- `frontend/src/pages/FormattingDetail.tsx`
- `frontend/src/pages/Skills.tsx`
- `frontend/src/pages/formatting.css`

## Scripts and tests

- `scripts/apply_formatting_integration.py`
- `scripts/build_full_source_from_original.py`
- `scripts/generate_sha256s.py`
- `scripts/formatting_integration_tree.py`
- `scripts/verify_coolify_bundle.py`
- `tests/conftest.py`
- `tests/test_apply_integration.py`
- `tests/test_build_full_source.py`
- `tests/test_opencode_control.py`
- `tests/test_runtime_workspace.py`
- `tests/test_skill_archive.py`
- `tests/test_opencode_client.py`
- `tests/test_formatting_migration_shape.py`
- `tests/test_formatting_api_static.py`
- `tests/test_formatting_outbox_dispatcher.py`
- `tests/test_formatting_repository.py`
- `tests/test_formatting_tasks_static.py`
- `tests/test_integration_tooling_static.py`
- `tests/test_verify_coolify_bundle.py`

## Deployment and docs

- `.env.formatting.example`
- `.env.coolify.manual.example`
- `.dockerignore`
- `docker-compose.yml`
- `COOLIFY_ENVIRONMENT_VARIABLES_AR.md`
- `UPLOAD_NOW_README_AR.md`
- `FULL_SOURCE_NOTICE.md`
- `SOURCE_COMPLETENESS_NOTICE_AR.md`
- `README.md`
- `README_INTEGRATION_AR.md`
- `VERIFICATION_REPORT.md`
- `COOLIFY_BUNDLE_VERIFICATION_REPORT.md`
- `APPLICATION_AUDIT_AND_COOLIFY_REPORT.md`
- `APPLICATION_ARCHITECTURE_AND_DEPLOYMENT_EN.md`
- `OPENCODE_CHATGPT_AND_SKILLS_AR.md`
- `REMEDIATION_EXECUTION_STATUS.md`
- `docs/DEPLOYMENT_CHECKLIST_AR.md`
- `docs/FORMATTING_ARCHITECTURE_AR.md`
- `docs/OPENCODE_CHATGPT_AND_SKILLS_AR.md`
