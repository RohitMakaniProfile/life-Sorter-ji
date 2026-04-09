import { useNavigate, useSearchParams } from 'react-router-dom';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { API_ROUTES, apiPost } from '../api';
import { IKSHAN_AUTH_TOKEN_KEY } from '../config/authStorage.ts';
import { getUserIdFromJwt } from '../api/authSession';

declare global {
  interface Window {
    google?: any;
  }
}

/**
 * Google Login Page
 *
 * Two modes of operation:
 * 1. New user login/signup: Creates or updates user with Google email
 * 2. Link email to existing account: When ?mode=link is passed, links email to current user
 */
export default function GoogleLoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const rawNext = params.get('next') || '';
  const mode = params.get('mode') || 'login'; // 'login' | 'link'
  const isLinkMode = mode === 'link';

  let next = '/chat';
  try {
    const decoded = rawNext ? decodeURIComponent(rawNext) : '';
    if (
      decoded &&
      decoded.length < 500 &&
      !decoded.includes('/login') &&
      !decoded.includes('/google-login')
    ) {
      next = decoded;
    }
  } catch {
    // ignore and keep default
  }

  // In link mode, default next to account page
  if (isLinkMode && !rawNext) {
    next = '/account';
  }

  const forceLogin = ['1', 'true', 'yes'].includes((params.get('force') || '').toLowerCase());
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const buttonRef = useRef<HTMLDivElement | null>(null);
  const didInitRef = useRef(false);

  const clientId = useMemo(
    () => (import.meta as any).env.VITE_GOOGLE_CLIENT_ID as string | undefined,
    []
  );

  // Get current user ID if in link mode
  const currentUserId = isLinkMode ? getUserIdFromJwt() : null;

  useEffect(() => {
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      const msg = String((event?.reason as any)?.message || event?.reason || '');
      if (msg.includes('identity-credentials-get') || msg.includes('failedWithIframeGetPermission')) {
        event.preventDefault();
      }
    };
    window.addEventListener('unhandledrejection', onUnhandledRejection);

    // In link mode, require existing JWT
    if (isLinkMode && !currentUserId) {
      setError('You must be signed in to link an email');
      return;
    }

    // In login mode, skip if already authenticated (unless force)
    if (!isLinkMode) {
      const existing = window.localStorage.getItem(IKSHAN_AUTH_TOKEN_KEY);
      if (existing && !forceLogin) {
        navigate(next, { replace: true });
        return;
      }
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
  }, [navigate, next, isLinkMode, currentUserId, forceLogin]);

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

            // Build request body
            const body: Record<string, string> = { idToken };
            if (isLinkMode && currentUserId) {
              body.link_to_user_id = currentUserId;
            }

            const data = (await apiPost(API_ROUTES.auth.googleExchange, body)) as {
              token?: string;
              detail?: string;
              isAdmin?: boolean;
              isSuperAdmin?: boolean;
            };

            const token = String(data?.token || '').trim();
            if (!token) throw new Error('Backend did not return a token');

            window.localStorage.setItem(IKSHAN_AUTH_TOKEN_KEY, token);
            navigate(next, { replace: true });
          } catch (e: any) {
            const msg = e?.message || 'Login failed';
            if (msg.includes('already linked')) {
              setError('This email is already linked to another account');
            } else {
              setError(msg);
            }
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
        text: isLinkMode ? 'continue_with' : 'signin_with',
        width: 320,
      });
    } catch (e: any) {
      setError(e?.message || 'Login failed');
    }
  }, [clientId, navigate, next, ready, isLinkMode, currentUserId]);

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md border border-zinc-800 rounded-xl p-6 bg-zinc-900">
        <div className="flex justify-center mb-4">
          <img src="/ikshan-logo.svg" alt="Ikshan" className="h-10 w-auto" />
        </div>
        <div className="text-sm uppercase tracking-wide text-zinc-400">
          {isLinkMode ? 'Link Email' : 'Sign In'}
        </div>
        <h1 className="text-xl font-semibold mt-1">
          {isLinkMode ? 'Connect Your Google Account' : 'Sign in with Google'}
        </h1>

        {isLinkMode && (
          <p className="mt-2 text-sm text-zinc-400">
            Link your Google email to your existing account. This will allow you to sign in using either your phone or Google.
          </p>
        )}

        <div className="mt-5 flex flex-col gap-3">
          <div className="flex justify-center">
            <div ref={buttonRef} />
          </div>

          <button
            className="w-full rounded-lg border border-zinc-700 hover:bg-zinc-800 px-4 py-2 text-sm"
            onClick={() => {
              if (isLinkMode) {
                navigate('/account', { replace: true });
              } else {
                window.localStorage.removeItem(IKSHAN_AUTH_TOKEN_KEY);
                navigate('/chat', { replace: true });
              }
            }}
          >
            {isLinkMode ? 'Cancel' : 'Back to chat'}
          </button>
        </div>

        {error && (
          <div className="mt-4 text-sm text-red-300 bg-red-950/40 border border-red-900 rounded-lg p-3">
            {error}
          </div>
        )}

        {!isLinkMode && (
          <div className="mt-4 text-xs text-zinc-500">
            Next: <span className="text-zinc-300">{next}</span>
          </div>
        )}

        {!clientId && (
          <div className="mt-3 text-xs text-amber-300 bg-amber-950/30 border border-amber-900 rounded-lg p-3">
            Missing <code className="text-amber-200">VITE_GOOGLE_CLIENT_ID</code>. Set it in your deployment env and rebuild.
          </div>
        )}
      </div>
    </div>
  );
}

