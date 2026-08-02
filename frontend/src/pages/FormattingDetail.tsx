import { Ban, Download, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { post } from '../api';
import { useFetch } from '../hooks/useFetch';
import type { FormattingJob } from '../formatting';
import './formatting.css';

const statusLabels: Record<string, string> = {
  queued: 'في الانتظار',
  running: 'جارٍ التنسيق',
  completed: 'مكتملة',
  failed: 'فشلت',
  cancelled: 'أُلغيت',
};

function AttemptHistory({
  sourceJobId,
  currentId,
}: {
  sourceJobId: string;
  currentId: string;
}) {
  const { data, loading, error } = useFetch<FormattingJob[]>(
    `/formatting/jobs?source_job_id=${encodeURIComponent(sourceJobId)}`,
    4000,
  );

  const attempts = [...(data ?? [])].sort(
    (left, right) => right.attempt_number - left.attempt_number,
  );

  return (
    <section className="panel attempt-history" aria-labelledby="attempt-history-title">
      <h2 id="attempt-history-title">سجل المحاولات</h2>
      {loading && !data && (
        <p className="muted-status" role="status">
          جارٍ تحميل المحاولات...
        </p>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {!!attempts.length && (
        <nav className="attempt-list" aria-label="محاولات تنسيق هذا التفريغ">
          {attempts.map((attempt) => {
            const isCurrent = attempt.id === currentId;
            return (
              <Link
                key={attempt.id}
                className={isCurrent ? 'current' : ''}
                to={`/formatting/${attempt.id}`}
                aria-current={isCurrent ? 'page' : undefined}
              >
                <span>المحاولة {attempt.attempt_number}</span>
                <span className={`attempt-status status-${attempt.status}`}>
                  {statusLabels[attempt.status] || attempt.status}
                </span>
                <small>{new Date(attempt.created_at).toLocaleString('ar-JO')}</small>
              </Link>
            );
          })}
        </nav>
      )}
      {!loading && !error && !attempts.length && (
        <p className="muted-status">لا توجد محاولات أخرى.</p>
      )}
    </section>
  );
}

export default function FormattingDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { data, loading, error, reload } = useFetch<FormattingJob>(
    `/formatting/jobs/${id}`,
    4000,
  );
  const [operation, setOperation] = useState<'rerun' | 'cancel' | null>(null);
  const [operationError, setOperationError] = useState('');

  async function rerun() {
    if (!data || operation || data.status === 'queued' || data.status === 'running') return;
    try {
      setOperation('rerun');
      setOperationError('');
      const next = await post<FormattingJob>(`/formatting/jobs/${id}/rerun`, {});
      navigate(`/formatting/${next.id}`);
    } catch (requestError) {
      setOperationError(
        requestError instanceof Error ? requestError.message : 'تعذرت إعادة التنسيق',
      );
    } finally {
      setOperation(null);
    }
  }

  async function cancel() {
    if (!data || operation || !['queued', 'running'].includes(data.status)) return;
    try {
      setOperation('cancel');
      setOperationError('');
      await post<FormattingJob>(`/formatting/jobs/${id}/cancel`, {});
      await reload();
    } catch (requestError) {
      setOperationError(
        requestError instanceof Error ? requestError.message : 'تعذر إلغاء التنسيق',
      );
    } finally {
      setOperation(null);
    }
  }

  if (loading && !data) {
    return <div className="center" role="status">جارٍ التحميل...</div>;
  }
  if (error && !data) {
    return <div className="alert error" role="alert">{error}</div>;
  }
  if (!data) return null;

  const active = data.status === 'queued' || data.status === 'running';

  return (
    <>
      <div className="page-title">
        <div>
          <h1>النسخة المنسقة</h1>
          <p>
            محاولة رقم {data.attempt_number} • {data.model_snapshot} •{' '}
            {data.reasoning_snapshot}
          </p>
        </div>
        <div className="format-title-actions" aria-busy={operation !== null || undefined}>
          {active && (
            <button
              className="danger"
              type="button"
              disabled={operation !== null}
              onClick={() => void cancel()}
            >
              <Ban size={16} />
              {operation === 'cancel' ? 'جارٍ الإلغاء...' : 'إلغاء التنسيق'}
            </button>
          )}
          <button
            type="button"
            disabled={active || operation !== null}
            onClick={() => void rerun()}
            title={active ? 'لا يمكن إعادة التنسيق قبل انتهاء المحاولة الحالية' : undefined}
          >
            <RefreshCw size={16} />
            {operation === 'rerun' ? 'جارٍ الإرسال...' : 'إعادة التنسيق'}
          </button>
        </div>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}
      {operationError && (
        <div className="alert error" role="alert">{operationError}</div>
      )}

      <section className="panel format-meta" aria-live="polite">
        <span>
          الحالة: <b>{statusLabels[data.status] || data.status}</b>
        </span>
        <span>
          التقدم: <b>{Math.round(data.progress)}%</b>{' '}
          <progress
            aria-label="تقدم التنسيق"
            max="100"
            value={Math.max(0, Math.min(100, data.progress))}
          />
        </span>
        <span>
          المهارة: <b>{data.skill_name_snapshot}</b>
        </span>
        <Link to={`/jobs/${data.source_job_id}`}>عرض التفريغ الأصلي</Link>
      </section>

      {data.error_message && (
        <div className="alert error" role="alert">{data.error_message}</div>
      )}

      {!!data.artifacts?.length && (
        <section className="panel">
          <h2>الملفات الناتجة</h2>
          <div className="artifact-list">
            {data.artifacts.map((artifact) => (
              <a
                key={artifact.id}
                href={`/api/formatting/artifacts/${artifact.id}/download`}
              >
                <Download size={15} />
                {artifact.file_name}
                <small>{Math.ceil(artifact.size_bytes / 1024)} KB</small>
              </a>
            ))}
          </div>
        </section>
      )}

      {data.output_preview && (
        <section className="panel formatted-preview">
          <h2>معاينة النص المنسق</h2>
          <pre>{data.output_preview}</pre>
        </section>
      )}

      <AttemptHistory sourceJobId={data.source_job_id} currentId={data.id} />
    </>
  );
}
