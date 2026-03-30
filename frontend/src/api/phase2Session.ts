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

export function getPhase2UserId(): string | null {
  const token = getAppJwt();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  const sub = payload?.sub;
  return typeof sub === 'string' && sub.trim() ? sub.trim() : null;
}

function getPhase2SessionIdFromJwt(): string | null {
  const token = getAppJwt();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  for (const key of ['sessionId', 'session_id', 'sid']) {
    const v = payload?.[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return null;
}

/** Fields the Phase 2 backend reads from JSON bodies and query params (`_actor_from_payload`). */
export function getPhase2ActorFields(): { userId?: string; sessionId?: string } {
  const userId = getPhase2UserId();
  const sessionId = getPhase2SessionIdFromJwt();
  const out: { userId?: string; sessionId?: string } = {};
  if (userId) out.userId = userId;
  if (sessionId) out.sessionId = sessionId;
  return out;
}
