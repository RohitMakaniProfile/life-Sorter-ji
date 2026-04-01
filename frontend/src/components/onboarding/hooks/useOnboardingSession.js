import { useRef, useCallback } from 'react';
import * as api from '../api';

export function useOnboardingSession() {
  const sessionIdRef = useRef(null);
  const sessionPromiseRef = useRef(null);

  const ensureSession = useCallback(async () => {
    if (sessionIdRef.current) return sessionIdRef.current;
    if (!sessionPromiseRef.current) {
      sessionPromiseRef.current = api
        .createSession()
        .then((data) => {
          sessionIdRef.current = data.session_id;
          return data.session_id;
        })
        .catch((err) => {
          sessionPromiseRef.current = null;
          throw err;
        });
    }
    return sessionPromiseRef.current;
  }, []);

  return { sessionIdRef, ensureSession };
}
