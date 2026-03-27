import { getApiBaseRequired } from '../config/apiBase';

const AUTH_TOKEN_KEY = 'ikshan-auth-token';

type Primitive = string | number | boolean | null;
type JsonValue = Primitive | JsonValue[] | { [k: string]: JsonValue };

function getAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

function withBase(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  const base = getApiBaseRequired();
  return `${base}${pathOrUrl}`;
}

function buildHeaders(headers?: HeadersInit, includeJsonContentType = false): Headers {
  const merged = new Headers(headers || {});
  if (includeJsonContentType && !merged.has('Content-Type')) {
    merged.set('Content-Type', 'application/json');
  }
  const token = getAuthToken();
  if (token && !merged.has('Authorization')) {
    merged.set('Authorization', `Bearer ${token}`);
  }
  return merged;
}

export async function apiRequest(pathOrUrl: string, init: RequestInit = {}): Promise<Response> {
  const hasBody = typeof init.body !== 'undefined' && init.body !== null;
  const headers = buildHeaders(init.headers, hasBody && typeof init.body === 'string');
  return fetch(withBase(pathOrUrl), {
    ...init,
    headers,
    credentials: init.credentials ?? 'include',
  });
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

