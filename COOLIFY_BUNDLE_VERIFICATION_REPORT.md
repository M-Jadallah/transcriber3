> **HISTORICAL VERIFICATION ONLY:** All commands and results in this report predate the current static-only edits and were not rerun. See [`REMEDIATION_EXECUTION_STATUS.md`](REMEDIATION_EXECUTION_STATUS.md) for current status.

# تقرير تاريخي لفحوص حزمة Coolify السابقة

**التاريخ:** 2 أغسطس 2026

## الفحوص المنفذة

- يُظهر الفحص النصي الحالي لـ`docker-compose.yml` الموحد 16 خدمة وست شبكات وتسعة Volumes؛ لم يُعد تشغيل محلل YAML بعد الإصلاحات الحالية.
- أضيفت قواعد Verifier للمصفوفات الدقيقة للشبكات وmounts، وفصل `edge` العامة عن `gateway` الداخلية، وعزل شبكتي خروج OpenCode وعمّال التفريغ، ولم تُشغّل.
- يرفض Verifier خاصية `ports` في كل خدمة، ويرفض `expose` إلا `80` في `gateway`، ولم يُشغّل بعد هذه التعديلات.
- فحص Python بواسطة `compileall`.
- التشغيل السابق لاختبارات الحزمة: **52 ناجحة، و1 متجاوزة**؛ لم تُعد الاختبارات بعد تغييرات المراجعة الساكنة.
- يتحقق `scripts/verify_coolify_bundle.py` نصيًا من المصدر الكامل وسياق البناء
  وأدوات `tools/formatting-integration/` المنسوخة، ويحلل `down_revision` و`depends_on`
  للمراجع المعلقة والدورات والترحيلات اللاحقة مع تحديد الرأس بواسطة
  `down_revision` فقط، كما يحتوي قواعد topology/health/secrets الدقيقة ومسحًا نهائيًا
  مغلقًا افتراضيًا لكل الشجرة. يضع Builder Backup خارج المشروع، ويحتفظ به حتى نجاح
  Verifier وإنشاء ZIP. لم يُشغّل أي من المسارين في هذه الدفعة الساكنة.
- أضيف ساكنًا عقد دقيق لمفاتيح Compose العلوية يرفض `include` و`extends` ومفتاح
  الدمج العلوي و`configs` و`secrets` وكل مفتاح غير متوقع. وأضيفت مفاتيح lifecycle
  وconfig/secret إلى مصفوفة التجاوزات الممنوعة لكل الخدمات، مع رفض `profiles`
  و`scale` و`deploy` بالكامل لضمان بقاء كل خدمة مطلوبة مفعلة افتراضيًا بنسخة واحدة.
  أضيفت اختبارات mutation ساكنة لهذه الحالات ولم تُشغّل.

## الأسرار التلقائية

```text
SERVICE_PASSWORD_64_POSTGRES
SERVICE_PASSWORD_64_ADMIN
SERVICE_HEX_128_SESSION
SERVICE_PASSWORD_64_OPENCODE
SERVICE_PASSWORD_64_REDIS
```

## حدود التحقق

لم يُنفذ بناء Docker فعلي داخل بيئة الإنشاء لعدم توفر Docker daemon، ولم تُنفذ مصادقة ChatGPT حقيقية لأنها تتطلب حساب المستخدم ومتصفح المصادقة. كما أن المصدر الأصلي الكامل للتطبيق غير موجود ضمن بيئة الإنشاء؛ راجع `SOURCE_COMPLETENESS_NOTICE_AR.md`. لا تعد هذه الحزمة وحدها إصدارًا قابلاً للنشر.

Verifier الحالي فحص بنيوي لا يثبت اكتمال المصدر الانتقالي ولا صحة Compose أو نجاح
الصور. يجب تشغيل `docker compose config` وبناء كل الصور فعليًا واختبار تطهير
`X-Forwarded-Proto` في Coolify كبوابات إصدار خارجية.
