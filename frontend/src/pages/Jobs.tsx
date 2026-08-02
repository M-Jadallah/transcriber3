import { useState } from 'react';
import { Link } from 'react-router-dom';
import { get, post } from '../api';
import { useFetch } from '../hooks/useFetch';
import FormatTranscriptButton from '../components/FormatTranscriptButton';
import type { FormattingJob } from '../formatting';

export type Job = {
  id: string;
  url: string;
  title?: string | null;
  status: string;
  language?: string | null;
  created_at: string;
  completed_at?: string | null;
};

const statusLabels: Record<string, string> = {
  pending: 'في الانتظار',
  queued: 'في الطابور',
  running: 'جارٍ التفريغ',
  completed: 'مكتملة',
  failed: 'فشلت',
  cancelled: 'أُلغيت',
};

export default function Jobs() {
  const { data: jobs, loading, error, reload } = useFetch<Job[]>('/jobs');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState('');

  // Pull the latest formatting attempt for each completed transcription job
  // so the row can show "view formatted" / "formatting in progress" inline.
  const completedJobIds = (jobs ?? [])
    .filter((j) => j.status === 'completed')
    .map((j) => j.id);

  const { data: latestFormatting } = useFetch<Record<string, FormattingJob>>(
    completedJobIds.length
      ? `/formatting/jobs/latest?job_ids=${encodeURIComponent(completedJobIds.join(','))}`
      : '',
    5000,
  );

  async function createJob(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !url.trim()) return;
    try {
      setBusy(true);
      setCreateError('');
      await post<Job>('/jobs', { url: url.trim() });
      setUrl('');
      await reload();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : 'تعذر إنشاء المهمة');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-title">
        <h1>تفريغ الفيديوهات</h1>
        <p>أدخل رابط فيديو أو قائمة تشغيل يوتيوب</p>
      </div>

      <form className="new-job-form" onSubmit={createJob}>
        <input
          type="url"
          placeholder="https://www.youtube.com/watch?v=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          disabled={busy}
        />
        <button className="primary" type="submit" disabled={busy || !url.trim()}>
          {busy ? 'جارٍ الإرسال...' : 'تفريغ'}
        </button>
      </form>

      {createError && <div className="alert error" role="alert">{createError}</div>}
      {error && <div className="alert error" role="alert">{error}</div>}

      {loading && !jobs && <p className="muted-status">جارٍ التحميل...</p>}

      {!!jobs?.length && (
        <table className="job-table">
          <thead>
            <tr>
              <th>العنوان</th>
              <th>الحالة</th>
              <th>تاريخ الإنشاء</th>
              <th>إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td>
                  <Link to={`/jobs/${job.id}`}>
                    {job.title || job.url}
                  </Link>
                </td>
                <td>
                  <span className={`status-badge status-${job.status}`}>
                    {statusLabels[job.status] || job.status}
                  </span>
                </td>
                <td>
                  <small>{new Date(job.created_at).toLocaleString('ar-JO')}</small>
                </td>
                <td>
                  <div className="row-actions">
                    <Link className="row-export-link" to={`/jobs/${job.id}`}>
                      عرض
                    </Link>
                    {job.status === 'completed' && (
                      <FormatTranscriptButton
                        sourceJobId={job.id}
                        latest={latestFormatting?.[job.id]}
                        onStarted={() => reload()}
                      />
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && !error && !jobs?.length && (
        <p className="muted-status">لا توجد مهام بعد.</p>
      )}
    </>
  );
}
