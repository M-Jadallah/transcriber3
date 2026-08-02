import { useState, useEffect } from 'react';
import { Link, Outlet, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { get, post, setSessionTokens, clearSessionTokens, getSessionToken } from './api';
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
      const result = await post<{
        message: string;
        username: string;
        session_token: string;
        csrf_token: string;
      }>('/auth/login', { username, password });

      // Store tokens in localStorage for hybrid auth (cookie + header)
      // This ensures the app works even if the browser rejects the Set-Cookie
      // header for any reason (Secure flag, SameSite, Domain matching, etc.)
      if (result.session_token) {
        setSessionTokens(result.session_token, result.csrf_token || '');
      }

      // Navigate to the main app. The Layout will verify auth via /auth/me,
      // which will now succeed because the Authorization header is sent.
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
  // Three auth states: 'loading' (check in flight), 'authenticated', 'unauthenticated'.
  // Plus an 'error' state for when the auth check fails due to network/timeout.
  const [user, setUser] = useState<string | null>(null);
  const [authState, setAuthState] = useState<'loading' | 'authenticated' | 'unauthenticated' | 'error'>('loading');
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    get<{ username: string }>('/auth/me')
      .then((data) => {
        if (!cancelled) {
          setUser(data.username);
          setAuthState('authenticated');
        }
      })
      .catch((err) => {
        if (cancelled) return;
        // If the error is a timeout or network error (status 0), show an error
        // state instead of redirecting to login. This prevents the user from
        // being bounced to /login when the backend is just slow to respond.
        if (err instanceof Error && err.message.includes('مهلة')) {
          setAuthState('error');
        } else if (err instanceof Error && err.message.includes('تعذر الاتصال')) {
          setAuthState('error');
        } else {
          clearSessionTokens();
          setAuthState('unauthenticated');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function retryAuth() {
    setAuthState('loading');
    try {
      const data = await get<{ username: string }>('/auth/me');
      setUser(data.username);
      setAuthState('authenticated');
    } catch (err) {
      if (err instanceof Error && (err.message.includes('مهلة') || err.message.includes('تعذر الاتصال'))) {
        setAuthState('error');
      } else {
        clearSessionTokens();
        setAuthState('unauthenticated');
      }
    }
  }

  async function logout() {
    try {
      await post('/auth/logout', {});
    } catch {
      // ignore
    }
    clearSessionTokens();
    setUser(null);
    setAuthState('unauthenticated');
    navigate('/login', { replace: true });
  }

  if (authState === 'loading') {
    return (
      <div className="center-container" role="status" aria-live="polite">
        <p>جارٍ التحقق...</p>
      </div>
    );
  }

  if (authState === 'error') {
    return (
      <div className="center-container">
        <div className="alert error" role="alert">
          تعذر الاتصال بالخادم. تأكد من أن الخدمة تعمل ثم أعد المحاولة.
        </div>
        <button className="primary" type="button" onClick={retryAuth}>
          إعادة المحاولة
        </button>
      </div>
    );
  }

  if (authState === 'unauthenticated') {
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
