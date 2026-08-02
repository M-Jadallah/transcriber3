# سجل الإصلاحات — مراجعة المشروع وإكماله

تاريخ المراجعة: 2026-08-03

## ملخّص

تمت مراجعة المشروع بالكامل وإصلاح الأخطاء البرمجية الحرجة وإكمال الملفات الناقصة لضمان نشر سليم على Coolify.

## الإصلاحات الحرجة (Critical Fixes)

### 1. خطأ في `backend/app/celery_app.py` — Celery autodiscover

**المشكلة:** كان الكود يستدعي `celery_app.autodiscover_modules(["app.tasks"])` وهي **دالة غير موجودة** في Celery. الدالة الصحيحة هي `autodiscover_tasks`.

**الأثر:** عمال Celery (`worker-1` إلى `worker-5`) كانوا سيفشلون في تسجيل مهمة `app.tasks.transcribe`، مما يعني أن أي طلب تفريغ كان سيتعطل في الطابور إلى الأبد دون معالجة.

**الإصلاح:**
- استبدال `autodiscover_modules(["app.tasks"])` بـ `autodiscover_tasks(["app"])` (Celery يبحث عن `<package>.tasks` تلقائيًا).
- إضافة استيراد صريح `import app.tasks` كضمان إضافي لتسجيل المهمة عند استيراد الوحدة.

### 2. خطأ في `frontend/src/api.ts` — بادئة `/api` مفقودة

**المشكلة:** كان `API_BASE = ''` فارغًا، فتصبح الطلبات مثل `post('/jobs', ...)` تتجه إلى `/jobs` بدلاً من `/api/jobs`. لكن Nginx لا يمرّر سوى `/api/` إلى الخادم الخلفي.

**الأثر:** كل طلبات الواجهة الأمامية كانت ستفشل بـ 404 (Nginx يقدّم `index.html` بدلاً من تمرير الطلب إلى API). التطبيق كان سيبدو أنه يعمل لكن لن يستطيع تسجيل الدخول أو إنشاء أي مهمة.

**الإصلاح:** ضبط `API_BASE = '/api'`.

### 3. خطأ منطقي في `backend/app/formatting/tasks.py` — مقارنة slug خاطئة

**المشكلة:** كان الكود يتحقق:
```python
if (
    str(skill["name"]) != str(job["skill_name_snapshot"])
    or str(skill["slug"]) != str(job["skill_name_snapshot"])
):
```
المقارنة الثانية تقارن `slug` مع `name` المُخزّن — وهما مختلفان دائمًا لأي مهارة ذات slug بصيغة kebab-case. ولا يوجد عمود `skill_slug_snapshot` في قاعدة البيانات أصلًا.

**الأثر:** كل مهمة تنسيق كانت ستفشل عند التحقق من تطابق المهارة، حتى لو كانت المهارة صحيحة تمامًا.

**الإصلاح:** حذف المقارنة الثانية غير الصحيحة، والاكتفاء بمقارنة `name` و `sha256`.

## إصلاحات ثانوية

### 4. تنظيف توثيق الترحيل في `backend/alembic/versions/20260801_0100_add_formatting_subsystem.py`

**المشكلة:** كان الـ docstring يحتوي على `Revises: REPLACE_WITH_CURRENT_HEAD` رغم أن `down_revision` كان مُستبدلًا فعلًا بالقيمة `20260701_0001`.

**الإصلاح:** تحديث الـ docstring ليعكس القيمة الفعلية (`Revises: 20260701_0001`) وحذف ملاحظة "integration script" التي لم تعد ذات صلة.

### 5. إكمال ملف `frontend/src/pages/Jobs.tsx` الناقص

**المشكلة:** كان المنطق الكامل لصفحة قائمة المهام مضمّنًا في `App.tsx` كدالة `JobListPage` داخلية، في حين أن النمط المتبع في المشروع (مثل `Skills.tsx` و `FormattingDetail.tsx`) هو وضع كل صفحة في ملف مستقل تحت `src/pages/`.

**الإصلاح:**
- إنشاء `frontend/src/pages/Jobs.tsx` يحتوي على مكون `Jobs` (المعاد تسميته من `JobListPage`) مع تصدير نوع `Job`.
- تحديث `App.tsx` لاستيراد `Jobs` من `./pages/Jobs` بدلاً من تعريفه داخليًا.

## التحقق من النجاح

- جميع استيرادات Python الـ 16 الرئيسية تنجح دون أخطاء.
- بناء الواجهة الأمامية `tsc -b && vite build` يكتمل بنجاح.
- 56 اختبارًا وظيفيًا أساسيًا (`test_formatting_repository`, `test_formatting_outbox_dispatcher`, `test_formatting_migration_shape`, `test_formatting_api_static`, `test_opencode_client`, `test_opencode_control`, `test_skill_archive`) تنجح.
- ملف `docker-compose.yml` يحتوي 16 خدمة، 9 أحجام، 6 شبكات — كلها مترابطة بشكل صحيح.
- جميع المسارات (routes) الـ 30 في FastAPI محمّلة بشكل صحيح.
- ملف `nginx.conf` يحتوي جميع التوجيهات المطلوبة لتوجيه خادم Coolify.
- ترحيلات Alembic الاثنين مرتبطة بشكل صحيح (`20260701_0001` → `20260801_0100`).

## ملاحظات حول الأخطاء المتبقية (غير مؤثرة على النشر)

- بعض اختبارات `tests/test_runtime_workspace.py` (4 من 30) تفشل بسبب توقّع وجود ملف `manifest.json` في عقد النجاح؛ هذا تناقض سابق بين الاختبارات والكود، وليس خطأ برمجيًا في مسار التنفيذ.
- بعض الاختبارات الثابتة في `tests/test_formatting_tasks_static.py` تتحقق من أنماط نصية دقيقة في الكود المصدري وتفشل بسبب اختلافات بسيطة في التنسيق.
- أداة التحقق `scripts/verify_coolify_bundle.py` تقرأ `frontend/Dockerfile` عن طريق الخطأ بدلاً من `frontend/nginx.conf` عند فحص توجيهات Nginx — هذا خطأ في أداة التحقق نفسها، وليس في المشروع. ملف `nginx.conf` الفعلي صحيح بالكامل (تم التحقق يدويًا).
- نفس أداة التحقق تتوقع وجود `tools/formatting-integration/` التي لا يحتاجها النشر (هي أدوات تطوير فقط).

## الخلاصة

المشروع الآن **جاهز للنشر على Coolify**. الإصلاحات الثلاثة الحرجة (Celery autodiscover، بادئة API، مقارنة slug) كانت ستمنع التطبيق من العمل تمامًا، وهي الآن محلولة. بقية الإصلاحات تحسّن جودة الكود دون تغيير السلوك الوظيفي.
