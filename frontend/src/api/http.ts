import { getApiBaseRequired } from '../config/apiBase';
import { IKSHAN_AUTH_TOKEN_KEY } from '../config/authStorage';

type Primitive = string | number | boolean | null;
type JsonValue = Primitive | JsonValue[] | { [k: string]: JsonValue };

function getAuthToken(): string | null {
  try {
    return localStorage.getItem(IKSHAN_AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

function withBase(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const base = getApiBaseRequired();
  return `${base}${pathOrUrl}`;
}

/** Pathname only, for choosing Bearer token and auth error handling. */
function pathForAuth(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    try {
      return new URL(pathOrUrl).pathname;
    } catch {
      return pathOrUrl;
    }
  }
  return pathOrUrl.split('?')[0];
}

function bearerTokenForPath(_path: string): string | null {
  return getAuthToken();
}

let authRedirect401Lock = false;

function maybeRedirectOn401(pathOrUrl: string): void {
  if (typeof window === 'undefined') return;
  try {
    const path = pathForAuth(pathOrUrl);
    const isAdminApi = path.startsWith('/api/v1/admin');
    const protectedApi =
      path.startsWith('/api/v1/ai-chat') ||
      path.startsWith('/api/agents') ||
      path.startsWith('/api/files/download') ||
      isAdminApi;
    if (!protectedApi) return;
    const p = window.location.pathname || '';
    if (p.includes('/admin/login')) return;
    if (authRedirect401Lock) return;
    authRedirect401Lock = true;
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.localStorage.removeItem(IKSHAN_AUTH_TOKEN_KEY);
    window.location.href = `/admin/login?mode=${isAdminApi ? 'admin' : 'internal'}&next=${next}`;
  } catch {
    // ignore
  }
  window.setTimeout(() => {
    authRedirect401Lock = false;
  }, 3000);
}

function buildHeaders(pathOrUrl: string, headers?: HeadersInit, includeJsonContentType = false): Headers {
  const merged = new Headers(headers || {});
  if (includeJsonContentType && !merged.has('Content-Type')) {
    merged.set('Content-Type', 'application/json');
  }
  const path = pathForAuth(pathOrUrl);
  const token = bearerTokenForPath(path);
  if (token && !merged.has('Authorization')) {
    merged.set('Authorization', `Bearer ${token}`);
  }
  return merged;
}

export async function apiRequest(pathOrUrl: string, init: RequestInit = {}): Promise<Response> {
  const hasBody = typeof init.body !== 'undefined' && init.body !== null;
  const headers = buildHeaders(pathOrUrl, init.headers, hasBody && typeof init.body === 'string');
  const res = await fetch(withBase(pathOrUrl), {
    ...init,
    headers,
    credentials: init.credentials ?? 'include',
  });
  if (res.status === 401) {
    maybeRedirectOn401(pathOrUrl);
  }
  return res;
}

export async function apiGet<T>(pathOrUrl: string, init: RequestInit = {}): Promise<T> {
  const res = await apiRequest(pathOrUrl, { ...init, method: 'GET' });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return (await res.json()) as T;
}

export async function apiPost<T>(pathOrUrl: string, body?: JsonValue, init: RequestInit = {}): Promise<T> {
  const res = await apiRequest(pathOrUrl, {
    ...init,
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string; message?: string }).detail || (detail as { message?: string }).message || `Request failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function apiDelete(pathOrUrl: string, init: RequestInit = {}): Promise<void> {
  const res = await apiRequest(pathOrUrl, { ...init, method: 'DELETE' });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
}

export async function apiGetText(pathOrUrl: string, init: RequestInit = {}): Promise<string> {
  const res = await apiRequest(pathOrUrl, { ...init, method: 'GET' });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.text();
}

