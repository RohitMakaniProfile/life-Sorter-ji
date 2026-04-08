import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { clsx } from 'clsx';
import { IKSHAN_AUTH_TOKEN_KEY } from '../config/authStorage';
import { apiPost } from '../api';
import { API_ROUTES } from '../api';
import { getUserIdFromJwt } from '../api/authSession';

type SendOtpResponse = {
  success: boolean;
  message?: string;
  detail?: string;
};

type VerifyOtpResponse = {
  success: boolean;
  verified?: boolean;
  message?: string;
  detail?: string;
  token?: string;
};

/**
 * Phone Verification Page
 *
 * Two modes of operation:
 * 1. New user login: Creates or updates user with phone number
 * 2. Link phone to existing account: When ?mode=link is passed, links phone to current user
 */
export default function PhoneVerifyPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const mode = params.get('mode') || 'login'; // 'login' | 'link'
  const isLinkMode = mode === 'link';
  const rawNext = params.get('next') || '';

  let next = '/chat';
  try {
    const decoded = rawNext ? decodeURIComponent(rawNext) : '';
    if (decoded && decoded.length < 500 && !decoded.includes('/phone-verify')) {
      next = decoded;
    }
  } catch {
    // ignore
  }

  // In link mode, default next to account page
  if (isLinkMode && !rawNext) {
    next = '/account';
  }

  const currentUserId = isLinkMode ? getUserIdFromJwt() : null;

  const [step, setStep] = useState('phone');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resendTimer, setResendTimer] = useState(0);

  // Check if user is authenticated in link mode
  if (isLinkMode && !currentUserId) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-zinc-950 text-zinc-100">
        <div className="w-full max-w-md border border-zinc-800 rounded-xl p-6 bg-zinc-900 text-center">
          <div className="w-14 h-14 bg-red-500/20 rounded-2xl flex items-center justify-center text-2xl mx-auto mb-4">
            ⚠️
          </div>
          <h2 className="text-lg font-semibold mb-2">Sign In Required</h2>
          <p className="text-sm text-zinc-400 mb-4">
            You must be signed in to link a phone number to your account.
          </p>
          <button
            onClick={() => navigate('/account', { replace: true })}
            className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold"
          >
            Go to Account
          </button>
        </div>
      </div>
    );
  }

  const startResendTimer = () => {
    setResendTimer(30);
    const t = setInterval(() => {
      setResendTimer((prev) => {
        if (prev <= 1) {
          clearInterval(t);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  const handleSendOtp = async () => {
    setError('');
    const cleaned = phone.replace(/\D/g, '');
    if (cleaned.length < 10) {
      setError('Enter a valid 10-digit mobile number');
      return;
    }
    setLoading(true);
    try {
      const data = await apiPost<SendOtpResponse>(API_ROUTES.auth.sendOtp, {
        phone_number: cleaned,
      });
      if (!data.success) {
        setError(data.message || data.detail || 'Failed to send OTP');
        return;
      }
      setStep('otp');
      startResendTimer();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error — please try again');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async () => {
    setError('');
    if (otp.length < 4) {
      setError('Enter the OTP sent to your phone');
      return;
    }
    setLoading(true);
    try {
      const body: Record<string, string> = {
        phone_number: phone.replace(/\D/g, ''),
        otp_code: otp,
      };

      // If in link mode, pass the current user ID
      if (isLinkMode && currentUserId) {
        body.link_to_user_id = currentUserId;
      }

      const data = await apiPost<VerifyOtpResponse>(API_ROUTES.auth.verifyOtp, body);
      if (!data.success) {
        const msg = data.message || data.detail || 'Verification failed';
        if (msg.includes('already linked')) {
          setError('This phone number is already linked to another account');
        } else {
          setError(msg);
        }
        return;
      }
      if (!data.verified) {
        setError('Incorrect OTP — please try again');
        return;
      }
      if (data.token) {
        try {
          window.localStorage.setItem(IKSHAN_AUTH_TOKEN_KEY, data.token);
        } catch {
          // ignore storage errors
        }
      }
      navigate(next, { replace: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Network error — please try again';
      if (msg.includes('already linked')) {
        setError('This phone number is already linked to another account');
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResend = () => {
    if (resendTimer > 0) return;
    setOtp('');
    setError('');
    setStep('phone');
  };

  const phoneInvalid = phone.replace(/\D/g, '').length < 10;
  const otpInvalid = otp.length < 4;
  const ctaDisabled = loading || (step === 'phone' ? phoneInvalid : otpInvalid);

  return (
    <div className="h-screen w-screen flex items-center justify-center bg-zinc-950 text-zinc-100">
      <div className="w-full max-w-md border border-zinc-800 rounded-xl p-6 bg-zinc-900">
        <div className="text-sm uppercase tracking-wide text-zinc-400">
          {isLinkMode ? 'Link Phone Number' : 'Sign In'}
        </div>
        <h1 className="text-xl font-semibold mt-1">
          {step === 'phone'
            ? (isLinkMode ? 'Add Your Phone Number' : 'Verify Your Number')
            : 'Enter OTP'}
        </h1>

        <p className="mt-2 text-sm text-zinc-400">
          {step === 'phone'
            ? isLinkMode
              ? 'Link your phone number to your account. This will allow you to sign in using either Google or your phone.'
              : 'Enter your mobile number to sign in'
            : `We sent a 6-digit OTP to +91 ${phone.replace(/\D/g, '').slice(-10)}`}
        </p>

        <div className="mt-5">
          {step === 'phone' ? (
            <div className="relative">
              <div className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-sm font-semibold text-zinc-400 select-none">
                +91
              </div>
              <input
                type="tel"
                maxLength={10}
                placeholder="98765 43210"
                value={phone}
                onChange={(e) => {
                  setPhone(e.target.value.replace(/\D/g, ''));
                  setError('');
                }}
                onKeyDown={(e) => e.key === 'Enter' && handleSendOtp()}
                autoFocus
                className={clsx(
                  'box-border w-full rounded-lg border bg-zinc-800 py-3 pr-4 pl-12 text-base tracking-wide text-zinc-100 outline-none focus:ring-2 focus:ring-violet-500',
                  error ? 'border-red-500' : 'border-zinc-700',
                )}
              />
            </div>
          ) : (
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="• • • • • •"
              value={otp}
              onChange={(e) => {
                setOtp(e.target.value.replace(/\D/g, ''));
                setError('');
              }}
              onKeyDown={(e) => e.key === 'Enter' && handleVerifyOtp()}
              autoFocus
              className={clsx(
                'box-border w-full rounded-lg border bg-zinc-800 py-3 text-center text-2xl font-bold tracking-[0.3em] text-zinc-100 outline-none focus:ring-2 focus:ring-violet-500',
                error ? 'border-red-500' : 'border-zinc-700',
              )}
            />
          )}
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="mt-4 flex flex-col gap-2">
          <button
            type="button"
            onClick={step === 'phone' ? handleSendOtp : handleVerifyOtp}
            disabled={ctaDisabled}
            className={clsx(
              'w-full rounded-lg py-3 text-sm font-bold text-white transition-all',
              ctaDisabled
                ? 'cursor-not-allowed bg-violet-400/50'
                : 'cursor-pointer bg-violet-600 hover:bg-violet-500',
            )}
          >
            {loading
              ? step === 'phone'
                ? 'Sending…'
                : 'Verifying…'
              : step === 'phone'
                ? 'Send OTP →'
                : (isLinkMode ? 'Verify & Link Phone' : 'Verify & Sign In')}
          </button>

          {step === 'otp' && (
            <button
              type="button"
              onClick={handleResend}
              disabled={resendTimer > 0}
              className={clsx(
                'cursor-pointer border-none bg-transparent py-1 text-sm',
                resendTimer > 0 ? 'cursor-default text-zinc-500' : 'text-violet-400 hover:text-violet-300',
              )}
            >
              {resendTimer > 0 ? `Resend OTP in ${resendTimer}s` : '← Change number / Resend'}
            </button>
          )}

          <button
            type="button"
            onClick={() => navigate(isLinkMode ? '/account' : '/chat', { replace: true })}
            className="w-full rounded-lg border border-zinc-700 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            Cancel
          </button>
        </div>

        <div className="mt-5 text-center text-xs text-zinc-500">
          🔒 Your number is only used for verification. We don't share it with anyone.
        </div>
      </div>
    </div>
  );
}
