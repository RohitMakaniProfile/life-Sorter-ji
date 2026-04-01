import { useState } from 'react';
import { clsx } from 'clsx';

const API_BASE = () => {
  const raw = import.meta.env.VITE_API_URL || '';
  return raw.replace(/\/+$/, '');
};

export default function OtpModal({ sessionId, onVerified }) {
  const [step, setStep] = useState('phone');
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSessionId, setOtpSessionId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resendTimer, setResendTimer] = useState(0);

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
      const res = await fetch(`${API_BASE()}/api/v1/auth/send-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, phone_number: cleaned }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        setError(data.message || data.detail || 'Failed to send OTP');
        return;
      }
      setOtpSessionId(data.otp_session_id);
      setStep('otp');
      startResendTimer();
    } catch {
      setError('Network error — please try again');
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
      const res = await fetch(`${API_BASE()}/api/v1/auth/verify-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, otp_session_id: otpSessionId, otp_code: otp }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        setError(data.message || data.detail || 'Verification failed');
        return;
      }
      if (!data.verified) {
        setError('Incorrect OTP — please try again');
        return;
      }
      onVerified();
    } catch {
      setError('Network error — please try again');
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
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/55 p-4 backdrop-blur-sm">
      <div className="flex w-full max-w-[420px] flex-col rounded-3xl bg-white px-8 py-9 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-600 to-violet-500 text-[26px]">
          🔐
        </div>

        <div className="mb-1.5 text-[22px] font-black text-gray-900">
          {step === 'phone' ? 'Verify Your Number' : 'Enter OTP'}
        </div>
        <div className="mb-7 text-[13.5px] leading-relaxed text-gray-500">
          {step === 'phone'
            ? 'Your personalised playbook is ready. Enter your mobile number to unlock it.'
            : `We sent a 6-digit OTP to +91 ${phone.replace(/\D/g, '').slice(-10)}`}
        </div>

        {step === 'phone' ? (
          <div className="relative mb-3">
            <div className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-sm font-semibold text-gray-700 select-none">
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
                'box-border w-full rounded-xl border-[1.5px] bg-gray-50 py-3.5 pr-4 pl-[50px] text-base tracking-wide text-gray-900 outline-none',
                error ? 'border-red-500' : 'border-gray-200',
              )}
            />
          </div>
        ) : (
          <div className="mb-3">
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
                'box-border w-full rounded-xl border-[1.5px] bg-gray-50 py-3.5 text-center text-[28px] font-extrabold tracking-[0.3em] text-gray-900 outline-none',
                error ? 'border-red-500' : 'border-gray-200',
              )}
            />
          </div>
        )}

        {error && (
          <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-600">
            {error}
          </div>
        )}

        <button
          type="button"
          onClick={step === 'phone' ? handleSendOtp : handleVerifyOtp}
          disabled={ctaDisabled}
          className={clsx(
            'mb-0 w-full rounded-xl border-none py-3.5 text-[15px] font-extrabold text-white transition-all',
            step === 'otp' && 'mb-3',
            ctaDisabled ? 'cursor-wait bg-violet-300' : 'cursor-pointer bg-gradient-to-br from-violet-600 to-violet-500',
          )}
        >
          {loading
            ? step === 'phone'
              ? 'Sending…'
              : 'Verifying…'
            : step === 'phone'
              ? 'Send OTP →'
              : 'Verify & Unlock Playbook 🚀'}
        </button>

        {step === 'otp' && (
          <button
            type="button"
            onClick={handleResend}
            disabled={resendTimer > 0}
            className={clsx(
              'cursor-pointer border-none bg-transparent py-1 text-[13px] font-semibold',
              resendTimer > 0 ? 'cursor-default text-gray-400' : 'text-violet-600',
            )}
          >
            {resendTimer > 0 ? `Resend OTP in ${resendTimer}s` : '← Change number / Resend'}
          </button>
        )}

        <div className="mt-5 text-center text-[11px] leading-relaxed text-gray-400">
          🔒 Your number is only used for verification. We don&apos;t share it with anyone.
        </div>
      </div>
    </div>
  );
}
