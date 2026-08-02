import { ExternalLink, KeyRound, LogOut, RefreshCw, Save, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { post, put } from '../api';
import {
  type FormattingSettings,
  type OpenCodeAuthStatus,
  type Reasoning,
} from '../formatting';
import { useFetch } from '../hooks/useFetch';
import '../pages/formatting.css';

type AuthFlow = {
  url: string;
  method: 'auto' | 'code';
  instructions?: string;
};

export default function FormattingSettingsPanel() {
  const { data, loading, error, reload } = useFetch<FormattingSettings>(
    '/formatting/settings',
  );
  const {
    data: auth,
    loading: authLoading,
    error: authLoadError,
    reload: reloadAuth,
  } = useFetch<OpenCodeAuthStatus>(
    '/formatting/auth/status',
    5000,
  );
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [model, setModel] = useState('');
  const [reasoning, setReasoning] = useState<Reasoning | ''>('');
  const [skill, setSkill] = useState('');
  const [message, setMessage] = useState('');
  const [messageIsError, setMessageIsError] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [providerId, setProviderId] = useState('openai');
  const [authMethod, setAuthMethod] = useState(0);
  const [authCode, setAuthCode] = useState('');
  const [authFlow, setAuthFlow] = useState<AuthFlow | null>(null);
  const [authInputs, setAuthInputs] = useState<Record<string, string>>({});
  const [authOperation, setAuthOperation] = useState<
    'connect' | 'callback' | 'logout' | 'refresh' | null
  >(null);

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setModel(data.default_model);
    setReasoning(data.default_reasoning);
    setSkill(data.default_skill_id || '');
  }, [data]);

  const providerChoices = useMemo(() => {
    if (!auth) return [];
    return Object.entries(auth.auth_methods)
      .filter(([, methods]) => methods.some((method) => method.type === 'oauth'))
      .map(([id, methods]) => ({ id, methods }));
  }, [auth]);

  useEffect(() => {
    if (!providerChoices.length) return;
    if (!providerChoices.some((provider) => provider.id === providerId)) {
      setProviderId(providerChoices[0].id);
      setAuthMethod(0);
    }
  }, [providerChoices, providerId]);

  const selectedMethods = useMemo(
    () =>
      (auth?.auth_methods[providerId] ?? []).filter(
        (method) => method.type === 'oauth',
      ),
    [auth, providerId],
  );

  const modelOptions = useMemo(() => {
    const values = new Set<string>();
    for (const provider of auth?.providers ?? []) {
      const providerName = provider.id || '';
      for (const [key, info] of Object.entries(provider.models ?? {})) {
        const modelId = info.id || key;
        values.add(modelId.includes('/') ? modelId : `${providerName}/${modelId}`);
      }
    }
    return [...values].filter(Boolean).sort();
  }, [auth]);

  async function save() {
    if (!data || enabled === null || !reasoning || saveBusy) return;
    try {
      setSaveBusy(true);
      setMessage('');
      await put<FormattingSettings>('/formatting/settings', {
        enabled,
        default_model: model,
        default_reasoning: reasoning,
        default_skill_id: skill || null,
      });
      setMessageIsError(false);
      setMessage('تم حفظ إعدادات التنسيق');
      await reload();
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error
          ? requestError.message
          : 'تعذر حفظ الإعدادات',
      );
    } finally {
      setSaveBusy(false);
    }
  }

  function validateAuthFlow(value: AuthFlow) {
    if (!value || (value.method !== 'auto' && value.method !== 'code')) {
      throw new Error('استجابة المصادقة غير صالحة');
    }
    let url: URL;
    try {
      url = new URL(value.url);
    } catch {
      throw new Error('رابط المصادقة غير صالح');
    }
    const localHttpHosts = new Set(['localhost', '127.0.0.1', '::1']);
    const safeProtocol =
      url.protocol === 'https:' ||
      (url.protocol === 'http:' && localHttpHosts.has(url.hostname));
    if (!safeProtocol || url.username || url.password) {
      throw new Error('بروتوكول رابط المصادقة غير مسموح');
    }
    return url.href;
  }

  async function connect() {
    if (authOperation) return;
    try {
      setAuthOperation('connect');
      setMessage('');
      const originalMethods = auth?.auth_methods[providerId] ?? [];
      const selected = selectedMethods[authMethod];
      const realIndex = originalMethods.findIndex((method) => method === selected);
      if (realIndex < 0) throw new Error('طريقة المصادقة غير متاحة');
      const flow = await post<AuthFlow>('/formatting/auth/start', {
        provider_id: providerId,
        method_index: realIndex,
        inputs: authInputs,
      });
      const authUrl = validateAuthFlow(flow);
      setAuthFlow({ ...flow, url: authUrl });
      setMessageIsError(false);
      setMessage('تم بدء المصادقة. أكمل الخطوات في الصفحة المفتوحة.');
      window.open(authUrl, '_blank', 'noopener,noreferrer');
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error
          ? requestError.message
          : 'تعذر بدء المصادقة',
      );
    } finally {
      setAuthOperation(null);
    }
  }

  async function disconnect() {
    if (authOperation) return;
    if (!confirm('فصل حساب ChatGPT عن عامل التنسيق؟ ستتوقف المهام الجديدة حتى إعادة الربط.')) return;
    try {
      setAuthOperation('logout');
      setMessage('');
      await post<{ success: boolean; restarting?: boolean }>('/formatting/auth/logout', {});
      setMessageIsError(false);
      setMessage('تم حذف بيانات المصادقة. تُعاد الآن تهيئة خدمة OpenCode...');
      setAuthFlow(null);
      window.setTimeout(() => void reloadAuth(), 4000);
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error
          ? requestError.message
          : 'تعذر فصل الحساب',
      );
    } finally {
      setAuthOperation(null);
    }
  }

  async function finish() {
    if (authOperation) return;
    try {
      setAuthOperation('callback');
      setMessage('');
      const originalMethods = auth?.auth_methods[providerId] ?? [];
      const selected = selectedMethods[authMethod];
      const realIndex = originalMethods.findIndex((method) => method === selected);
      if (realIndex < 0) throw new Error('طريقة المصادقة غير متاحة');
      const result = await post<{ success: boolean }>('/formatting/auth/callback', {
        provider_id: providerId,
        method_index: realIndex,
        code: authCode || null,
      });
      if (!result.success) throw new Error('لم يكتمل ربط الحساب');
      setMessageIsError(false);
      setMessage('تم إرسال رمز المصادقة. جاري التحقق من حالة الحساب...');
      setAuthFlow(null);
      setAuthCode('');
      await reloadAuth();
    } catch (requestError) {
      setMessageIsError(true);
      setMessage(
        requestError instanceof Error
          ? requestError.message
          : 'تعذر إكمال المصادقة',
      );
    } finally {
      setAuthOperation(null);
    }
  }

  async function refreshAuth() {
    if (authOperation) return;
    try {
      setAuthOperation('refresh');
      await reloadAuth();
    } finally {
      setAuthOperation(null);
    }
  }

  const formReady = Boolean(data) && enabled !== null && reasoning !== '';

  return (
    <section className="panel formatting-settings" aria-busy={saveBusy || undefined}>
      <div className="section-heading">
        <Sparkles />
        <div>
          <h2>التنسيق بالذكاء الاصطناعي</h2>
          <p>إعدادات مستقلة لا تغيّر التفريغ الأصلي.</p>
        </div>
      </div>

      {loading && !data && (
        <div className="muted-status" role="status">
          جارٍ تحميل الإعدادات...
        </div>
      )}
      {error && <div className="alert error" role="alert">{error}</div>}
      {message && (
        <div
          className={`alert ${messageIsError ? 'error' : ''}`}
          role={messageIsError ? 'alert' : 'status'}
          aria-live={messageIsError ? 'assertive' : 'polite'}
        >
          {message}
        </div>
      )}

      <div className="settings-grid">
        <label>
          <span>تفعيل الميزة</span>
          <input
            type="checkbox"
            checked={enabled ?? false}
            disabled={!formReady || saveBusy}
            onChange={(event) => setEnabled(event.target.checked)}
          />
        </label>
        <label>
          <span>النموذج</span>
          <input
            list="formatting-models"
            value={model}
            disabled={!formReady || saveBusy}
            onChange={(event) => setModel(event.target.value)}
            placeholder="openai/gpt-5.6-sol"
          />
          <datalist id="formatting-models">
            {modelOptions.map((item) => (
              <option value={item} key={item} />
            ))}
          </datalist>
        </label>
        <label>
          <span>مستوى التفكير</span>
          <select
            value={reasoning}
            disabled={!formReady || saveBusy}
            onChange={(event) => setReasoning(event.target.value as Reasoning)}
          >
            <option value="low">منخفض</option>
            <option value="medium">متوسط</option>
            <option value="high">عالٍ</option>
            <option value="xhigh">عالٍ جدًا</option>
          </select>
        </label>
        <label>
          <span>المهارة الافتراضية</span>
          <select
            value={skill}
            disabled={!formReady || saveBusy}
            onChange={(event) => setSkill(event.target.value)}
          >
            <option value="">اختر مهارة</option>
            {data?.skills.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <button
        className="primary"
        type="button"
        disabled={!formReady || saveBusy}
        onClick={() => void save()}
      >
        <Save size={16} />
        {saveBusy ? 'جارٍ الحفظ...' : 'حفظ الإعدادات'}
      </button>

      <hr />

      <div className="auth-card">
        <div>
          <h3>
            <KeyRound size={18} /> حساب ChatGPT عبر OpenCode
          </h3>
          <p aria-live="polite">
            {authLoading && !auth
              ? 'جارٍ التحقق من حالة OpenCode...'
              : auth?.connected
              ? `الحساب مرتبط: ${auth.connected_providers.join('، ')}`
              : auth?.available
                ? 'OpenCode يعمل، لكن لا يوجد مزود مرتبط بعد'
                : auth?.error || 'خدمة OpenCode غير متاحة'}
          </p>
          {authLoadError && (
            <p className="inline-error" role="alert">{authLoadError}</p>
          )}
        </div>
        <div className="auth-card-status" aria-busy={authOperation !== null || undefined}>
          <span className={auth?.connected ? 'status-dot ok' : 'status-dot'}>
            {auth?.connected ? 'متصل' : 'غير متصل'}
          </span>
          <button
            type="button"
            disabled={authOperation !== null}
            onClick={() => void refreshAuth()}
          >
            <RefreshCw size={15} />
            {authOperation === 'refresh' ? 'جارٍ التحديث...' : 'تحديث'}
          </button>
          {auth?.connected && (
            <button
              className="danger"
              type="button"
              disabled={authOperation !== null}
              onClick={() => void disconnect()}
            >
              <LogOut size={15} />
              {authOperation === 'logout' ? 'جارٍ الفصل...' : 'فصل الحساب'}
            </button>
          )}
        </div>
      </div>

      {!auth?.connected && auth?.available && providerChoices.length > 0 && (
        <div className="auth-actions">
          <select
            aria-label="مزود المصادقة"
            value={providerId}
            disabled={authOperation !== null}
            onChange={(event) => {
              setProviderId(event.target.value);
              setAuthMethod(0);
              setAuthInputs({});
            }}
          >
            {providerChoices.map((provider) => (
              <option value={provider.id} key={provider.id}>
                {provider.id}
              </option>
            ))}
          </select>
          <select
            aria-label="طريقة المصادقة"
            value={authMethod}
            disabled={authOperation !== null}
            onChange={(event) => {
              setAuthMethod(Number(event.target.value));
              setAuthInputs({});
            }}
          >
            {selectedMethods.map((method, index) => (
              <option key={`${method.label}-${index}`} value={index}>
                {method.label}
              </option>
            ))}
          </select>
          {selectedMethods[authMethod]?.prompts?.map((prompt) => (
            <input
              key={prompt.key}
              type={prompt.type === 'password' ? 'password' : 'text'}
              value={authInputs[prompt.key] || ''}
              disabled={authOperation !== null}
              onChange={(event) =>
                setAuthInputs((current) => ({
                  ...current,
                  [prompt.key]: event.target.value,
                }))
              }
              placeholder={prompt.placeholder || prompt.label}
              aria-label={prompt.label}
            />
          ))}
          <button
            className="secondary"
            type="button"
            disabled={authOperation !== null || !selectedMethods[authMethod]}
            onClick={() => void connect()}
          >
            <ExternalLink size={16} />
            {authOperation === 'connect' ? 'جارٍ بدء الربط...' : 'بدء ربط الحساب'}
          </button>
          <button
            type="button"
            disabled={authOperation !== null}
            onClick={() => void refreshAuth()}
          >
            <RefreshCw size={16} />
            {authOperation === 'refresh' ? 'جارٍ التحديث...' : 'تحديث الحالة'}
          </button>
        </div>
      )}

      {authFlow && (
        <div className="auth-flow">
          <p>{authFlow.instructions || 'أكمل المصادقة في الصفحة المفتوحة ثم عد إلى هنا.'}</p>
          <a href={authFlow.url} target="_blank" rel="noreferrer">
            فتح صفحة المصادقة
          </a>
          {authFlow.method === 'code' && (
            <>
              <input
                aria-label="رمز المصادقة"
                value={authCode}
                disabled={authOperation !== null}
                onChange={(event) => setAuthCode(event.target.value)}
                placeholder="ألصق الرمز هنا"
              />
              <button
                className="primary"
                type="button"
                disabled={authOperation !== null}
                onClick={() => void finish()}
              >
                {authOperation === 'callback' ? 'جارٍ إكمال الربط...' : 'إكمال الربط'}
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
