import { useRef, useState } from 'react';
import { CheckCircle2, PackageOpen, Power, Trash2, Upload } from 'lucide-react';
import { api, del, post } from '../api';
import { useFetch } from '../hooks/useFetch';
import type { FormattingSkill } from '../formatting';
import './formatting.css';

export default function Skills() {
  const { data, loading, error, reload } = useFetch<FormattingSkill[]>(
    '/formatting/skills?include_disabled=true',
  );
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [messageIsError, setMessageIsError] = useState(false);

  async function upload(file?: File) {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
      setBusy(true);
      setMessage('');
      await api<FormattingSkill>('/formatting/skills', {
        method: 'POST',
        body: form,
      });
      setMessageIsError(false);
      setMessage('تم فحص المهارة وحفظ إصدارها بنجاح');
      await reload();
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error
          ? requestError.message
          : 'فشل رفع المهارة',
      );
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  }

  async function disable(skill: FormattingSkill) {
    if (!confirm(`تعطيل المهارة «${skill.name}»؟ لن تتأثر المهام السابقة.`)) {
      return;
    }
    try {
      const result = await del<{ message: string }>(
        `/formatting/skills/${skill.id}`,
      );
      setMessageIsError(false);
      setMessage(result.message);
      await reload();
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error ? requestError.message : 'فشل التعطيل',
      );
    }
  }

  async function enable(skill: FormattingSkill) {
    try {
      const result = await post<{ message: string }>(
        `/formatting/skills/${skill.id}/enable`,
        {},
      );
      setMessageIsError(false);
      setMessage(result.message);
      await reload();
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error ? requestError.message : 'فشل التفعيل',
      );
    }
  }

  return (
    <>
      <div className="page-title">
        <div>
          <h1>مهارات التنسيق</h1>
          <p>
            ارفع ملف ZIP، وسيقوم النظام بفحصه واستخراج الإصدار وحفظه تلقائيًا.
          </p>
        </div>
        <button
          className="primary"
          type="button"
          disabled={busy}
          aria-busy={busy || undefined}
          onClick={() => input.current?.click()}
        >
          <Upload size={17} />
          {busy ? 'جارٍ الفحص...' : 'رفع مهارة ZIP'}
        </button>
        <input
          ref={input}
          hidden
          type="file"
          disabled={busy}
          aria-label="اختيار ملف مهارة ZIP"
          accept=".zip,application/zip"
          onChange={(event) => void upload(event.target.files?.[0])}
        />
      </div>

      {message && (
        <div
          className={`alert ${messageIsError ? 'error' : ''}`}
          role={messageIsError ? 'alert' : 'status'}
          aria-live={messageIsError ? 'assertive' : 'polite'}
        >
          {message}
        </div>
      )}
      {error && <div className="alert error" role="alert">{error}</div>}

      <section className="panel skill-grid">
        {data?.map((skill) => (
          <article
            className={`skill-card ${skill.is_enabled ? '' : 'disabled'}`}
            key={skill.id}
          >
            <PackageOpen size={28} />
            <div>
              <h3>{skill.name}</h3>
              <p>{skill.description}</p>
              <small>
                البصمة: {skill.sha256.slice(0, 12)} •{' '}
                {new Date(skill.created_at).toLocaleDateString('ar-JO')}
              </small>
            </div>
            <span className={skill.is_enabled ? 'skill-ok' : 'skill-disabled'}>
              {skill.is_enabled ? <CheckCircle2 size={15} /> : <Power size={15} />}
              {skill.is_enabled ? 'مفعلة' : 'معطلة'}
            </span>
            {skill.is_enabled ? (
              <button
                className="danger compact-button"
                type="button"
                onClick={() => void disable(skill)}
              >
                <Trash2 size={15} />
                تعطيل
              </button>
            ) : (
              <button
                className="secondary compact-button"
                type="button"
                onClick={() => void enable(skill)}
              >
                <Power size={15} />
                تفعيل
              </button>
            )}
          </article>
        ))}
        {!loading && !data?.length && (
          <div className="empty">لم تُرفع أي مهارة بعد.</div>
        )}
      </section>
    </>
  );
}
