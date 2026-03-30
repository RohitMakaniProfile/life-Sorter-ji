import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { coreApi } from '../../api';
import { IKSHAN_AUTH_TOKEN_KEY, IKSHAN_USER_EMAIL_KEY, IKSHAN_USER_NAME_KEY } from '../../config/authStorage';
import { phase2Path } from '../constants';

declare global {
  interface Window {
    google?: any;
  }
}

export default function InternalGoogleLoginPage({ mode }: { mode: 'internal' | 'admin' }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const rawNext = params.get('next') || '';
  let next = phase2Path('chat');
  try {
    const decoded = rawNext ? decodeURIComponent(rawNext) : '';
    if (
      decoded &&
      decoded.length < 500 &&
      !decoded.includes('/phase2/login-internal') &&
      !decoded.includes('/phase2/login-admin')
    ) {
      next = decoded.startsWith('/') ? decoded : phase2Path(decoded.replace(/^\//, ''));
    }
  } catch {
    // keep default
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
      if (msg.includes('identity-credentials-get') || msg.includes('failedWithIframeGetPermission')) {
        event.preventDefault();
      }
    };
    window.addEventListener('unhandledrejection', onUnhandledRejection);

    const existing = window.localStorage.getItem(IKSHAN_AUTH_TOKEN_KEY);
    if (existing && !forceLogin) {
      navigate(next, { replace: true });
      return () => window.removeEventListener('unhandledrejection', onUnhandledRejection);
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
  }, [navigate, next, forceLogin]);

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
        use_fedcm_for_prompt: true,
        callback: async (response: any) => {
          setLoading(true);
          try {
            const idToken = String(response?.credential || '').trim();
            if (!idToken) throw new Error('Missing credential from Google');

            let payload: { sub?: string; email?: string; name?: string; picture?: string };
            try {
              const b64 = idToken.split('.')[1];
              const pad = '='.repeat((4 - (b64.length % 4)) % 4);
              payload = JSON.parse(atob(b64.replace(/-/g, '+').replace(/_/g, '/') + pad));
            } catch {
              throw new Error('Invalid Google credential');
            }

            // Same flow as Phase 1 (`ChatBotNew`): agent session + POST /api/v1/auth/google
            const created = await coreApi.createAgentSession();
            const session_id = String((created as { session_id?: string })?.session_id || '').trim();
            if (!session_id) {
              throw new Error('Server did not return a session id. Check POST /api/v1/agent/session and VITE_API_URL.');
            }
            const data = await coreApi.googleAuth({
              session_id,
              google_id: String(payload.sub || ''),
              email: String(payload.email || ''),
              name: String(payload.name || ''),
              avatar_url: String(payload.picture || ''),
            });

            if (!data?.success || !data?.token) {
              throw new Error(String((data as any)?.detail || (data as any)?.message || 'Google login failed'));
            }

            window.localStorage.setItem(IKSHAN_AUTH_TOKEN_KEY, data.token);
            const emailOut = String((data.user as { email?: string } | undefined)?.email || payload.email || '').trim();
            const nameOut = String((data.user as { name?: string } | undefined)?.name || payload.name || '').trim();
            if (emailOut) window.localStorage.setItem(IKSHAN_USER_EMAIL_KEY, emailOut);
            if (nameOut) window.localStorage.setItem(IKSHAN_USER_NAME_KEY, nameOut);
            navigate(next, { replace: true });
          } catch (e: any) {
            setError(e?.message || 'Login failed');
          } finally {
            setLoading(false);
          }
        },
      });

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
            type="button"
            className="w-full rounded-lg border border-zinc-700 hover:bg-zinc-800 px-4 py-2 text-sm"
            onClick={() => navigate(phase2Path('chat'), { replace: true })}
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
            Missing <code className="text-amber-200">VITE_GOOGLE_CLIENT_ID</code>. Set it in your deployment env and
            rebuild.
          </div>
        )}

        {loading && <p className="mt-2 text-xs text-zinc-500">Signing in…</p>}
      </div>
    </div>
  );
}
