import { Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { startFormatting, type FormattingJob } from '../formatting';

type Props = {
  sourceJobId: string;
  latest?: FormattingJob;
  onStarted?: (job: FormattingJob) => void;
};

export default function FormatTranscriptButton({
  sourceJobId,
  latest,
  onStarted,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = latest && ['queued', 'running'].includes(latest.status);

  async function start() {
    try {
      setBusy(true);
      setError('');
      const job = await startFormatting(sourceJobId);
      onStarted?.(job);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'تعذر بدء التنسيق',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="format-action-wrap" aria-live="polite">
      {latest?.status === 'completed' ? (
        <Link className="row-export-link format-link" to={`/formatting/${latest.id}`}>
          <Sparkles size={14} />
          عرض المنسق
        </Link>
      ) : latest?.status === 'failed' ? (
        <button
          className="row-export-link format-link"
          type="button"
          disabled={busy}
          onClick={start}
        >
          <Sparkles size={14} />
          {busy ? 'جارٍ الإرسال...' : 'إعادة التنسيق'}
        </button>
      ) : (
        <button
          className="row-export-link format-link"
          type="button"
          disabled={busy || Boolean(running)}
          onClick={start}
        >
          <Sparkles size={14} />
          {running
            ? `جارٍ التنسيق ${Math.round(latest?.progress ?? 0)}%`
            : busy
              ? 'جارٍ الإرسال...'
              : 'تنسيق بالذكاء الاصطناعي'}
        </button>
      )}
      {error && (
        <small className="inline-error" role="alert">{error}</small>
      )}
    </div>
  );
}
