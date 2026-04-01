import { useState } from 'react';

const API_BASE = () => {
  const raw = import.meta.env.VITE_API_URL || '';
  return raw.replace(/\/+$/, '');
};

export default function OtpModal({ sessionId, onVerified }) {
  const [step, setStep] = useState('phone'); // 'phone' | 'otp'
  const [phone, setPhone] = useState('');
  const [otp, setOtp] = useState('');
  const [otpSessionId, setOtpSessionId] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [resendTimer, setResendTimer] = useState(0);

  const startResendTimer = () => {
    setResendTimer(30);
    const t = setInterval(() => {
      setResendTimer(prev => {
        if (prev <= 1) { clearInterval(t); return 0; }
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

  const handleResend = async () => {
    if (resendTimer > 0) return;
    setOtp('');
    setError('');
    setStep('phone');
  };

  return (
    /* Backdrop */
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '16px',
    }}>
      {/* Card */}
      <div style={{
        background: '#fff', borderRadius: 24, padding: '36px 32px',
        width: '100%', maxWidth: 420,
        boxShadow: '0 24px 60px rgba(0,0,0,0.18)',
        display: 'flex', flexDirection: 'column', gap: 0,
      }}>
        {/* Icon */}
        <div style={{
          width: 56, height: 56, borderRadius: 16,
          background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 26, marginBottom: 20,
        }}>🔐</div>

        {/* Heading */}
        <div style={{ fontSize: 22, fontWeight: 900, color: '#111827', marginBottom: 6 }}>
          {step === 'phone' ? 'Verify Your Number' : 'Enter OTP'}
        </div>
        <div style={{ fontSize: 13.5, color: '#6b7280', marginBottom: 28, lineHeight: 1.6 }}>
          {step === 'phone'
            ? 'Your personalised playbook is ready. Enter your mobile number to unlock it.'
            : `We sent a 6-digit OTP to +91 ${phone.replace(/\D/g, '').slice(-10)}`}
        </div>

        {/* Input */}
        {step === 'phone' ? (
          <div style={{ position: 'relative', marginBottom: 12 }}>
            <div style={{
              position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
              fontSize: 14, color: '#374151', fontWeight: 600, userSelect: 'none',
            }}>+91</div>
            <input
              type="tel"
              maxLength={10}
              placeholder="98765 43210"
              value={phone}
              onChange={e => { setPhone(e.target.value.replace(/\D/g, '')); setError(''); }}
              onKeyDown={e => e.key === 'Enter' && handleSendOtp()}
              autoFocus
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '14px 16px 14px 50px',
                border: `1.5px solid ${error ? '#ef4444' : '#e5e7eb'}`,
                borderRadius: 12, fontSize: 16, outline: 'none',
                color: '#111827', background: '#f9fafb',
                letterSpacing: '0.05em',
              }}
            />
          </div>
        ) : (
          <div style={{ marginBottom: 12 }}>
            <input
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="• • • • • •"
              value={otp}
              onChange={e => { setOtp(e.target.value.replace(/\D/g, '')); setError(''); }}
              onKeyDown={e => e.key === 'Enter' && handleVerifyOtp()}
              autoFocus
              style={{
                width: '100%', boxSizing: 'border-box',
                padding: '14px 16px', textAlign: 'center',
                border: `1.5px solid ${error ? '#ef4444' : '#e5e7eb'}`,
                borderRadius: 12, fontSize: 28, letterSpacing: '0.3em',
                outline: 'none', color: '#111827', background: '#f9fafb',
                fontWeight: 800,
              }}
            />
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{
            fontSize: 12.5, color: '#dc2626', marginBottom: 12,
            padding: '8px 12px', background: '#fef2f2', borderRadius: 8,
            border: '1px solid #fecaca',
          }}>
            {error}
          </div>
        )}

        {/* CTA Button */}
        <button
          onClick={step === 'phone' ? handleSendOtp : handleVerifyOtp}
          disabled={loading || (step === 'phone' ? phone.replace(/\D/g,'').length < 10 : otp.length < 4)}
          style={{
            width: '100%', padding: '14px',
            background: loading || (step === 'phone' ? phone.replace(/\D/g,'').length < 10 : otp.length < 4)
              ? '#c4b5fd' : 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
            border: 'none', borderRadius: 12,
            color: '#fff', fontSize: 15, fontWeight: 800,
            cursor: loading ? 'wait' : 'pointer',
            transition: 'all .2s',
            marginBottom: step === 'otp' ? 12 : 0,
          }}
        >
          {loading
            ? (step === 'phone' ? 'Sending…' : 'Verifying…')
            : (step === 'phone' ? 'Send OTP →' : 'Verify & Unlock Playbook 🚀')}
        </button>

        {/* Resend / back */}
        {step === 'otp' && (
          <button
            onClick={handleResend}
            disabled={resendTimer > 0}
            style={{
              background: 'none', border: 'none', cursor: resendTimer > 0 ? 'default' : 'pointer',
              fontSize: 13, color: resendTimer > 0 ? '#9ca3af' : '#7c3aed',
              fontWeight: 600, padding: '4px 0',
            }}
          >
            {resendTimer > 0 ? `Resend OTP in ${resendTimer}s` : '← Change number / Resend'}
          </button>
        )}

        {/* Privacy note */}
        <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 20, textAlign: 'center', lineHeight: 1.6 }}>
          🔒 Your number is only used for verification. We don't share it with anyone.
        </div>
      </div>
    </div>
  );
}
