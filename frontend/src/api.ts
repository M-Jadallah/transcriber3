/**
 * API client for communicating with the backend.
 *
 * All requests are relative to the current origin so that Nginx proxies
 * /api/* to the FastAPI backend transparently.
 *
 * HYBRID AUTH:
 * - Primary: cookies (session + csrf_token) set by the server.
 * - Fallback: session_token stored in localStorage, sent via the
 *   Authorization: Bearer header. This bypasses all cookie-related
 *   issues (Secure flag, SameSite, Domain matching, etc.) and ensures
 *   the app works even if the browser silently rejects the Set-Cookie
 *   header.
 *
 * CSRF protection (cookie-based auth only):
 * - The server sets a csrf_token cookie and the client echoes it back
 *   via the X-CSRF-Token header on state-changing requests.
 * - When using header-based auth (Authorization: Bearer), CSRF is
 *   inherently protected because the browser doesn't auto-attach the
 *   Authorization header to cross-site requests.
 */

const API_BASE = '/api';
const SESSION_TOKEN_KEY = 'transcriber3_session_token';
const CSRF_TOKEN_KEY = 'transcriber3_csrf_token';
const REQUEST_TIMEOUT_MS = 15000;

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ---------------------------------------------------------------------------
// Token management (localStorage-based fallback for cookies)
// ---------------------------------------------------------------------------

export function setSessionTokens(sessionToken: string, csrfToken: string): void {
  try {
    localStorage.setItem(SESSION_TOKEN_KEY, sessionToken);
    localStorage.setItem(CSRF_TOKEN_KEY, csrfToken);
  } catch {
    // localStorage might be unavailable (private browsing, etc.)
    // Fall back to cookie-based auth only.
  }
}

export function clearSessionTokens(): void {
  try {
    localStorage.removeItem(SESSION_TOKEN_KEY);
    localStorage.removeItem(CSRF_TOKEN_KEY);
  } catch {
    // ignore
  }
}

export function getSessionToken(): string | null {
  try {
    return localStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
}

function getCsrfToken(): string | null {
  // Try localStorage first (set by login response), then fall back to cookie
  try {
    const stored = localStorage.getItem(CSRF_TOKEN_KEY);
    if (stored) return stored;
  } catch {
    // ignore
  }
  const match = document.cookie
    .split('; ')
    .find((row) => row.startsWith('csrf_token='));
  return match ? decodeURIComponent(match.split('=')[1]) : null;
}

// ---------------------------------------------------------------------------
// Request helper with timeout and hybrid auth
// ---------------------------------------------------------------------------

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> ?? {}),
  };

  // Do not set Content-Type for FormData (browser sets it with boundary)
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = headers['Content-Type'] ?? 'application/json';
  }

  // Attach Authorization header if we have a session token (hybrid auth)
  const sessionToken = getSessionToken();
  if (sessionToken) {
    headers['Authorization'] = `Bearer ${sessionToken}`;
  }

  // Attach CSRF token to state-changing requests (for cookie-based auth)
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    const csrf = getCsrfToken();
    if (csrf) {
      headers['X-CSRF-Token'] = csrf;
    }
  }

  // Add a timeout so the UI never hangs indefinitely
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
      credentials: 'same-origin',
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'انتهت مهلة الطلب. تحقق من الاتصال بالخادم.');
    }
    throw new ApiError(0, 'تعذر الاتصال بالخادم');
  }
  clearTimeout(timeoutId);

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || body.message || body.error || message;
    } catch {
      // ignore parse errors
    }
    // If we get 401, clear stale tokens
    if (response.status === 401) {
      clearSessionTokens();
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T;
  }

  return response.json();
}

export function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  return request<T>(path, options);
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET' });
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body instanceof FormData ? body : JSON.stringify(body),
  });
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' });
}
