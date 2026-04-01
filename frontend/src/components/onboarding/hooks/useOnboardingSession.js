import { useRef, useCallback } from 'react';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';

const STORAGE_SESSION_KEY = 'life-sorter-onboarding-session-id';
const STORAGE_ROW_ID_KEY = 'life-sorter-onboarding-row-id';

function readStoredSessionId() {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(STORAGE_SESSION_KEY);
  } catch {
    return null;
  }
}

function persistSessionPayload(data) {
  if (typeof window === 'undefined' || !data?.session_id) return;
  try {
    localStorage.setItem(STORAGE_SESSION_KEY, data.session_id);
    if (data.id) localStorage.setItem(STORAGE_ROW_ID_KEY, data.id);
  } catch {
    /* ignore quota / private mode */
  }
}

export function useOnboardingSession() {
  const sessionIdRef = useRef(null);
  const sessionPromiseRef = useRef(null);

  /**
   * Resolves session_id. On first create, optional `initialFields` (e.g. outcome, domain) are sent
   * with POST /onboarding so the new row is inserted with those columns set.
   */
  const ensureSession = useCallback(async (initialFields = {}) => {
    if (!sessionIdRef.current) {
      const stored = readStoredSessionId();
      if (stored) sessionIdRef.current = stored;
    }
    if (sessionIdRef.current) return sessionIdRef.current;

    if (!sessionPromiseRef.current) {
      const body =
        initialFields && typeof initialFields === 'object' && Object.keys(initialFields).length > 0
          ? initialFields
          : {};
      sessionPromiseRef.current = apiPost(API_ROUTES.onboarding.upsert, body ?? {})
        .then((data) => {
          sessionIdRef.current = data.session_id;
          persistSessionPayload(data);
          return data.session_id;
        })
        .catch((err) => {
          sessionPromiseRef.current = null;
          throw err;
        });
    }
    return sessionPromiseRef.current;
  }, []);

  return { sessionIdRef, ensureSession, storageSessionKey: STORAGE_SESSION_KEY };
}
