import { useState, useEffect } from 'react';
import { Link, Outlet, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { get, post } from './api';
import { useFetch } from './hooks/useFetch';
import FormatTranscriptButton from './components/FormatTranscriptButton';
import FormattingNavigationLink from './components/FormattingNavigationLink';
import FormattingSettingsPanel from './components/FormattingSettingsPanel';
import FormattingDetail from './pages/FormattingDetail';
import Skills from './pages/Skills';
import Jobs, { type Job } from './pages/Jobs';
import type { FormattingJob } from './formatting';
import './App.css';

/* -------------------------------------------------------------------------- */
/*  Types                                                                      */
/* -------------------------------------------------------------------------- */

type JobDetail = Job & {
  transcript?: { id: number; text: string } | null;
  exports?: { id: number; format: string; file_name: string; size_bytes: number }[];
};

/* -------------------------------------------------------------------------- */
/*  Login Page                                                                 */
/* -------------------------------------------------------------------------- */

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    try {
      setBusy(true);
      setError('');
      await post<{ message: string }>('/auth/login', { username, password });
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر تسجيل الدخول');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center-container">
      <form className="login-form" onSubmit={submit}>
        <h1>مفّرغ اليوتيوب</h1>
        {error && <div className="alert error" role="alert">{error}</div>}
        <input
          type="text"
          placeholder="اسم المستخدم"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <input
          type="password"
          placeholder="كلمة المرور"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
        <button className="primary" type="submit" disabled={busy}>
          {busy ? 'جارٍ الدخول...' : 'تسجيل الدخول'}
        </button>
      </form>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Layout                                                                     */
/* -------------------------------------------------------------------------- */

function Layout() {
  const [user, setUser] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    get<{ username: string }>('/auth/me')
      .then((data) => setUser(data.username))
      .catch(() => setUser(null));
  }, []);

  async function logout() {
    try {
      await post('/auth/logout', {});
    } catch {
      // ignore
    }
    setUser(null);
    navigate('/login');
  }

  if (user === null) {
    return <NavigateToLogin />;
  }

  return (
    <div className="app-layout">
      <header className="app-header">
        <nav>
          <Link to="/" className="logo">مفّرغ اليوتيوب</Link>
          <Link to="/">الرئيسية</Link>
          <FormattingNavigationLink />
          <Link to="/settings">الإعدادات</Link>
        </nav>
        <div className="header-actions">
          <span>{user}</span>
          <button type="button" onClick={logout}>خروج</button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

function NavigateToLogin() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate('/login', { replace: true });
  }, [navigate]);
  return null;
}

/* -------------------------------------------------------------------------- */
/*  Job Detail Page                                                            */
/* -------------------------------------------------------------------------- */

function JobDetailPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { data: job, loading, error, reload } = useFetch<JobDetail>(`/jobs/${id}`, 4000);
  const [formattingJob, setFormattingJob] = useState<FormattingJob | null>(null);

  if (loading && !job) return <div className="center" role="status">جارٍ التحميل...</div>;
  if (error && !job) return <div className="alert error" role="alert">{error}</div>;
  if (!job) return null;

  const statusLabels: Record<string, string> = {
    pending: 'في الانتظار',
    queued: 'في الطابور',
    running: 'جارٍ التفريغ',
    completed: 'مكتملة',
    failed: 'فشلت',
    cancelled: 'أُلغيت',
  };

  return (
    <>
      <div className="page-title">
        <div>
          <h1>{job.title || 'تفريغ'}</h1>
          <p>
            <a href={job.url} target="_blank" rel="noreferrer">{job.url}</a>
          </p>
        </div>
        <span className={`status-badge status-${job.status}`}>
          {statusLabels[job.status] || job.status}
        </span>
      </div>

      {job.transcript?.text && (
        <section className="panel">
          <h2>النص المفرّغ</h2>
          <pre className="transcript-text">{job.transcript.text}</pre>
        </section>
      )}

      {job.exports?.length && (
        <section className="panel">
          <h2>الملفات</h2>
          <div className="export-list">
            {job.exports.map((exp) => (
              <a
                key={exp.id}
                className="export-link"
                href={`/api/jobs/${id}/exports/${exp.id}/download`}
              >
                {exp.format.toUpperCase()} ({Math.ceil(exp.size_bytes / 1024)} KB)
              </a>
            ))}
          </div>
        </section>
      )}

      {job.status === 'completed' && (
        <FormatTranscriptButton
          sourceJobId={id}
          latest={formattingJob ?? undefined}
          onStarted={(j) => setFormattingJob(j)}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Settings Page                                                              */
/* -------------------------------------------------------------------------- */

function SettingsPage() {
  return (
    <>
      <div className="page-title">
        <h1>الإعدادات</h1>
      </div>
      <FormattingSettingsPanel />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  App Router                                                                 */
/* -------------------------------------------------------------------------- */

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Jobs />} />
        <Route path="/jobs/:id" element={<JobDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/skills" element={<Skills />} />
        <Route path="/formatting/:id" element={<FormattingDetail />} />
      </Route>
    </Routes>
  );
}
