import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getApiBaseRequired } from '../../config/apiBase';

declare global {
  interface Window {
    google?: any;
  }
}

const STORAGE_KEY = 'ikshan.phase2.jwt';

export default function InternalGoogleLoginPage({ mode }: { mode: 'internal' | 'admin' }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const rawNext = params.get('next') || '';
  let next = '/chat';
  try {
    const decoded = rawNext ? decodeURIComponent(rawNext) : '';
    // Ignore pathological next values (e.g. recursive login URLs) to prevent loops.
    if (
      decoded &&
      decoded.length < 500 &&
      !decoded.includes('/phase2/login-internal') &&
      !decoded.includes('/phase2/login-admin')
    ) {
      next = decoded;
    }
  } catch {
    // ignore and keep default
  }
  const forceLogin = ['1', 'true', 'yes'].includes((params.get('force') || '').toLowerCase());
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clientId = useMemo(() => (import.meta as any).env.VITE_GOOGLE_CLIENT_ID as string | undefined, []);
  const API_BASE = useMemo(() => getApiBaseRequired(), []);

  useEffect(() => {
    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && !forceLogin) {
      // eslint-disable-next-line no-console
      console.log('[phase2 login] reusing existing JWT', {
        forceLogin,
        storageKey: STORAGE_KEY,
        tokenPrefix: existing ? String(existing).slice(0, 18) : null,
      });
      navigate(next, { replace: true });
      return;
    }

    const t0 = Date.now();
    const timer = window.setInterval(() => {
      if (window.google?.accounts?.id) {
        setReady(true);
        window.clearInterval(timer);
      }
      if (Date.now() - t0 > 5000) {
        window.clearInterval(timer);
        setReady(false);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [navigate, next]);

  const start = async () => {
    setError(null);
    if (!clientId) {
      setError('Google Sign-In is not configured (missing VITE_GOOGLE_CLIENT_ID).');
      return;
    }
    if (!window.google?.accounts?.id) {
      setError('Google Sign-In library not loaded. Please refresh and try again.');
      return;
    }

    setLoading(true);
    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response: any) => {
          try {
            const idToken = String(response?.credential || '').trim();
            if (!idToken) throw new Error('Missing credential from Google');

            const res = await fetch(`${API_BASE}/api/phase2/auth/google/exchange`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ idToken }),
            });

            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              throw new Error(String((data as any)?.detail || 'Login failed'));
            }

            const token = String((data as any)?.token || '').trim();
            if (!token) throw new Error('Backend did not return a token');

            window.localStorage.setItem(STORAGE_KEY, token);
            // eslint-disable-next-line no-console
            console.log('[phase2 login] backend exchange result', {
              isAdmin: (data as any)?.isAdmin,
              isSuperAdmin: (data as any)?.isSuperAdmin,
              tokenPrefix: token.slice(0, 18),
            });
            navigate(next, { replace: true });
          } catch (e: any) {
            setError(e?.message || 'Login failed');
          } finally {
            setLoading(false);
          }
        },
      });

      window.google.accounts.id.prompt();
    } catch (e: any) {
      setError(e?.message || 'Login failed');
      setLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md border border-zinc-800 rounded-xl p-6 bg-zinc-900">
        <div className="text-sm uppercase tracking-wide text-zinc-400">
          {mode === 'admin' ? 'Phase2 Admin Login' : 'Phase2 Internal Login'}
        </div>
        <h1 className="text-xl font-semibold mt-1">Sign in with Google</h1>
        <p className="text-sm text-zinc-400 mt-2">
          This page is not linked from the UI. Only allowlisted internal emails can sign in.
        </p>

        <div className="mt-5 flex flex-col gap-3">
          <button
            className="w-full rounded-lg bg-violet-600 hover:bg-violet-500 disabled:bg-zinc-700 px-4 py-2 font-medium"
            onClick={start}
            disabled={!ready || loading}
          >
            {loading ? 'Signing in…' : (ready ? 'Continue with Google' : 'Loading Google…')}
          </button>

          <button
            className="w-full rounded-lg border border-zinc-700 hover:bg-zinc-800 px-4 py-2 text-sm"
            onClick={() => {
              window.localStorage.removeItem(STORAGE_KEY);
              navigate('/chat', { replace: true });
            }}
          >
            Back to Phase2
          </button>
        </div>

        {error && (
          <div className="mt-4 text-sm text-red-300 bg-red-950/40 border border-red-900 rounded-lg p-3">
            {error}
          </div>
        )}

        <div className="mt-4 text-xs text-zinc-500">
          Next: <span className="text-zinc-300">{next}</span>
        </div>
      </div>
    </div>
  );
}

