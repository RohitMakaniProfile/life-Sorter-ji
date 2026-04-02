import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { IKSHAN_AUTH_TOKEN_KEY } from '../../config/authStorage';
import { apiPost } from '../../api/http';
import { API_ROUTES } from '../../api/routes';

declare global {
  interface Window {
    google?: any;
  }
}

const STORAGE_KEY = IKSHAN_AUTH_TOKEN_KEY;

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
      !decoded.includes('/login-internal') &&
      !decoded.includes('/login-admin')
    ) {
      next = decoded;
    }
  } catch {
    // ignore and keep default
  }
  const forceLogin = ['1', 'true', 'yes'].includes((params.get('force') || '').toLowerCase());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const buttonRef = useRef<HTMLDivElement | null>(null);
  const didInitRef = useRef(false);

  const clientId = useMemo(() => (import.meta as any).env.VITE_GOOGLE_CLIENT_ID as string | undefined, []);

  useEffect(() => {
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const msg = String((event?.reason as any)?.message || event?.reason || '');
      // Some browsers surface a noisy GSI/FedCM rejection without useful UX impact.
      if (msg.includes('identity-credentials-get') || msg.includes('failedWithIframeGetPermission')) {
        event.preventDefault();
      }
    };
    window.addEventListener('unhandledrejection', onUnhandledRejection);

    const existing = window.localStorage.getItem(STORAGE_KEY);
    if (existing && !forceLogin) {
      // eslint-disable-next-line no-console
      console.log('[auth login] reusing existing JWT', {
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
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('unhandledrejection', onUnhandledRejection);
    };
  }, [navigate, next]);

  useEffect(() => {
    setError(null);
    if (!clientId) return;
    if (!ready) return;
    if (!window.google?.accounts?.id) return;
    if (!buttonRef.current) return;
    if (didInitRef.current) return;

    didInitRef.current = true;
    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        // Opt-in to FedCM (Google is migrating One Tap / prompts).
        use_fedcm_for_prompt: true,
        callback: async (response: any) => {
          setLoading(true);
          try {
            const idToken = String(response?.credential || '').trim();
            if (!idToken) throw new Error('Missing credential from Google');

            const data = (await apiPost(API_ROUTES.auth.googleExchange, { idToken })) as {
              token?: string;
              detail?: string;
              isAdmin?: boolean;
              isSuperAdmin?: boolean;
            };

            const token = String(data?.token || '').trim();
            if (!token) throw new Error('Backend did not return a token');

            window.localStorage.setItem(STORAGE_KEY, token);
            // eslint-disable-next-line no-console
            console.log('[auth login] backend exchange result', {
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

      // Use the supported rendered button instead of One Tap prompt().
      buttonRef.current.innerHTML = '';
      window.google.accounts.id.renderButton(buttonRef.current, {
        theme: 'filled_black',
        size: 'large',
        shape: 'rectangular',
        text: 'continue_with',
        width: 320,
      });
    } catch (e: any) {
      setError(e?.message || 'Login failed');
    }
  }, [clientId, navigate, next, ready]);

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
          <div className="flex justify-center">
            <div ref={buttonRef} />
          </div>

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

        {!clientId && (
          <div className="mt-3 text-xs text-amber-300 bg-amber-950/30 border border-amber-900 rounded-lg p-3">
            Missing <code className="text-amber-200">VITE_GOOGLE_CLIENT_ID</code>. Set it in your deployment env and rebuild.
          </div>
        )}
      </div>
    </div>
  );
}

