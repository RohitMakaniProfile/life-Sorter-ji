import { IKSHAN_AUTH_TOKEN_KEY } from '../config/authStorage';

function getAppJwt(): string | null {
  try {
    const raw = localStorage.getItem(IKSHAN_AUTH_TOKEN_KEY);
    if (!raw?.trim()) return null;
    return raw.trim();
  } catch {
    return null;
  }
}

export function getJwtPayload(): Record<string, unknown> | null {
  const token = getAppJwt();
  if (!token) return null;
  return decodeJwtPayload(token);
}

export function getJwtTokenPrefix(): string | null {
  const token = getAppJwt();
  if (!token) return null;
  return String(token).slice(0, 18);
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length < 2) return null;
    const payloadB64Url = parts[1];
    const payloadB64 = payloadB64Url.replace(/-/g, '+').replace(/_/g, '/');
    const pad = '='.repeat((4 - (payloadB64.length % 4)) % 4);
    const json = atob(payloadB64 + pad);
    const o = JSON.parse(json) as unknown;
    return typeof o === 'object' && o !== null && !Array.isArray(o) ? (o as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function getUserIdFromJwt(): string | null {
  const payload = getJwtPayload();
  const sub = payload?.sub;
  return typeof sub === 'string' && sub.trim() ? sub.trim() : null;
}

export function getIsSuperAdmin(): boolean {
  const payload = getJwtPayload();
  return Boolean(payload?.super);
}

export function getIsAdmin(): boolean {
  const payload = getJwtPayload();
  return Boolean(payload?.admin);
}

export function getEmailFromJwt(): string | null {
  const payload = getJwtPayload();
  const email = payload?.email;
  return typeof email === 'string' && email.trim() ? email.trim() : null;
}

export function getPhoneNumberFromJwt(): string | null {
  const payload = getJwtPayload();
  const phone = payload?.phone_number;
  return typeof phone === 'string' && phone.trim() ? phone.trim() : null;
}

export function getNameFromJwt(): string | null {
  const payload = getJwtPayload();
  const name = payload?.name;
  return typeof name === 'string' && name.trim() ? name.trim() : null;
}

function getOnboardingSessionIdFromJwt(): string | null {
  const token = getAppJwt();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  for (const key of ['onboarding_session_id', 'sessionId', 'session_id', 'sid']) {
    const v = payload?.[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return null;
}

/** Actor fields read by backend APIs from payload/query. */
export function getAuthActorFields(): { userId?: string; sessionId?: string } {
  const userId = getUserIdFromJwt();
  const sessionId = getOnboardingSessionIdFromJwt();
  const out: { userId?: string; sessionId?: string } = {};
  if (userId) out.userId = userId;
  if (sessionId) out.sessionId = sessionId;
  return out;
}
