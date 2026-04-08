import { useRef, useCallback } from 'react';
import { apiPost, apiGet } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { getUserIdFromJwt } from '../../../api/authSession';

const STORAGE_SESSION_KEY = 'doable-claw-onboarding-session-id';
const STORAGE_ROW_ID_KEY = 'doable-claw-onboarding-row-id';

function isAuthenticatedUser() {
  return Boolean(getUserIdFromJwt());
}

function readStoredSessionId() {
  if (typeof window === 'undefined') return null;
  try {
    return localStorage.getItem(STORAGE_SESSION_KEY);
  } catch {
    return null;
  }
}

function persistSessionPayload(data, { persistToStorage = true } = {}) {
  if (typeof window === 'undefined' || !data?.session_id) return;
  if (!persistToStorage) return;
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
    const isAuth = isAuthenticatedUser();
    if (!sessionIdRef.current) {
      const stored = isAuth ? null : readStoredSessionId();
      if (stored) sessionIdRef.current = stored;
    }
    if (sessionIdRef.current) return sessionIdRef.current;

    if (!sessionPromiseRef.current) {
      sessionPromiseRef.current = (async () => {
        if (isAuth) {
          // Authenticated users should resolve by user identity first; don't use local session storage.
          try {
            const state = await apiGet(API_ROUTES.onboarding.state(null, getUserIdFromJwt()));
            if (state?.session_id) {
              sessionIdRef.current = state.session_id;
              return state.session_id;
            }
          } catch {
            // no existing onboarding row for this user yet
          }
        }

        const body =
          initialFields && typeof initialFields === 'object' && Object.keys(initialFields).length > 0
            ? initialFields
            : {};
        const data = await apiPost(API_ROUTES.onboarding.upsert, body ?? {});
        sessionIdRef.current = data.session_id;
        persistSessionPayload(data, { persistToStorage: !isAuth });
        return data.session_id;
      })().catch((err) => {
        sessionPromiseRef.current = null;
        throw err;
      });
    }
    return sessionPromiseRef.current;
  }, []);

  /**
   * Update onboarding with the given fields. If the backend creates a new session
   * (because the old one was complete), updates the stored session_id.
   */
  const updateOnboarding = useCallback(async (fields) => {
    const isAuth = isAuthenticatedUser();
    const sid = sessionIdRef.current || (isAuth ? null : readStoredSessionId());

    const data = await apiPost(
      API_ROUTES.onboarding.upsert,
      sid ? { session_id: sid, ...fields } : { ...fields },
    );
    if (data?.session_id) {
      sessionIdRef.current = data.session_id;
      persistSessionPayload(data, { persistToStorage: !isAuth });
    }

    // If backend created a new session (old one was complete), update our refs
    if (data?.new_session && data?.session_id) {
      sessionIdRef.current = data.session_id;
      sessionPromiseRef.current = null; // Clear the promise so ensureSession works fresh
      persistSessionPayload(data, { persistToStorage: !isAuth });
    }

    return data;
  }, []);

  /**
   * Fetch the current onboarding state from the backend for session restoration.
   * Prefers user_id based lookup if authenticated, falls back to session_id.
   * Returns null if no stored session exists or the session is not found.
   */
  const getSessionState = useCallback(async () => {
    const userId = getUserIdFromJwt();
    const storedId = readStoredSessionId();

    console.log('[getSessionState] userId:', userId, 'storedId:', storedId);

    // If neither user_id nor session_id is available, return null
    if (!userId && !storedId) {
      console.log('[getSessionState] No userId or storedId, returning null');
      return null;
    }

    try {
      // Backend will use user_id if provided, otherwise session_id
      const url = API_ROUTES.onboarding.state(storedId, userId);
      console.log('[getSessionState] Fetching state from:', url);
      const state = await apiGet(url);
      console.log('[getSessionState] State received:', state);
      // Set sessionIdRef if we got a valid response
      if (state?.session_id) {
        sessionIdRef.current = state.session_id;
        // Persist only for guest users.
        persistSessionPayload(state, { persistToStorage: !userId });
      }
      return state;
    } catch (err) {
      console.log('[getSessionState] Error:', err, 'status:', err?.status);
      // If session not found (404), clear stored session
      if (err?.status === 404) {
        try {
          localStorage.removeItem(STORAGE_SESSION_KEY);
          localStorage.removeItem(STORAGE_ROW_ID_KEY);
        } catch {
          /* ignore */
        }
      }
      console.warn('Failed to restore onboarding session:', err?.message || err);
      return null;
    }
  }, []);

  /**
   * Clear the stored session (e.g., to start fresh).
   */
  const clearSession = useCallback(() => {
    sessionIdRef.current = null;
    sessionPromiseRef.current = null;
    try {
      localStorage.removeItem(STORAGE_SESSION_KEY);
      localStorage.removeItem(STORAGE_ROW_ID_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  return { sessionIdRef, ensureSession, updateOnboarding, getSessionState, clearSession, storageSessionKey: STORAGE_SESSION_KEY };
}
