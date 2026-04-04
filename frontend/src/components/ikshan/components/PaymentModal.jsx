import { useState } from 'react';

const API_BASE = () => (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
const AMOUNT = 499;

const FEATURES = [
  '🔍 Deep competitor & market research',
  '📊 Full business intelligence report',
  '🤖 AI research agent — multi-step analysis',
  '💡 Personalized growth strategy',
  '📁 Downloadable report & insights',
];

export default function PaymentModal({ sessionId, customerPhone, onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handlePay = async () => {
    setError('');
    setLoading(true);
    try {
      const returnUrl = `${API_BASE()}/api/v1/payments/callback`;
      const res = await fetch(`${API_BASE()}/api/v1/payments/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: AMOUNT,
          customer_id: sessionId || `guest_${Date.now()}`,
          customer_email: '',
          customer_phone: customerPhone || '',
          return_url: returnUrl,
          description: 'Ikshan Deep Analysis — Stage 2 AI Research',
          udf1: 'stage2_chat',
          udf2: sessionId || '',
        }),
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        setError(data.error || data.detail || 'Failed to initiate payment');
        return;
      }

      // Redirect to JusPay payment page
      const payUrl = data.payment_links?.web || data.payment_links?.mobile;
      if (payUrl) {
        window.location.href = payUrl;
      } else {
        setError('Payment URL not received. Please try again.');
      }
    } catch {
      setError('Network error — please try again');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 16,
    }}>
      <div style={{
        background: '#fff', borderRadius: 24, width: '100%', maxWidth: 440,
        boxShadow: '0 24px 60px rgba(0,0,0,0.2)',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          background: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
          padding: '28px 28px 24px',
          position: 'relative',
        }}>
          <button onClick={onClose} style={{
            position: 'absolute', top: 14, right: 16,
            background: 'rgba(255,255,255,0.15)', border: 'none',
            color: '#fff', width: 30, height: 30, borderRadius: '50%',
            cursor: 'pointer', fontSize: 16, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}>✕</button>

          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.75)', fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', marginBottom: 8 }}>
            Unlock Stage 2
          </div>
          <div style={{ fontSize: 26, fontWeight: 900, color: '#fff', lineHeight: 1.2, marginBottom: 6 }}>
            Deep Analysis
          </div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.8)', lineHeight: 1.6 }}>
            Let our AI research agent go deep on your business — competitors, market gaps, and a full growth blueprint.
          </div>

          {/* Price badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'baseline', gap: 4,
            marginTop: 16, background: 'rgba(255,255,255,0.15)',
            borderRadius: 12, padding: '8px 16px',
          }}>
            <span style={{ fontSize: 13, color: 'rgba(255,255,255,0.7)', fontWeight: 600 }}>₹</span>
            <span style={{ fontSize: 36, fontWeight: 900, color: '#fff', lineHeight: 1 }}>{AMOUNT}</span>
            <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>one-time</span>
          </div>
        </div>

        {/* Features */}
        <div style={{ padding: '20px 28px 8px' }}>
          <div style={{ fontSize: 11, color: '#9ca3af', fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 12 }}>
            What you get
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
            {FEATURES.map((f, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontSize: 13.5, color: '#374151', lineHeight: 1.4 }}>
                <span>{f}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{ margin: '12px 28px 0', padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, fontSize: 12.5, color: '#dc2626' }}>
            {error}
          </div>
        )}

        {/* CTA */}
        <div style={{ padding: '20px 28px 28px' }}>
          <button
            onClick={handlePay}
            disabled={loading}
            style={{
              width: '100%', padding: '15px',
              background: loading ? '#c4b5fd' : 'linear-gradient(135deg,#6366f1,#8b5cf6)',
              border: 'none', borderRadius: 14,
              color: '#fff', fontSize: 16, fontWeight: 800,
              cursor: loading ? 'wait' : 'pointer',
              boxShadow: '0 4px 20px rgba(99,102,241,0.35)',
              transition: 'all .2s',
            }}
          >
            {loading ? 'Redirecting to payment…' : `Pay ₹${AMOUNT} & Unlock →`}
          </button>
          <div style={{ fontSize: 11, color: '#9ca3af', textAlign: 'center', marginTop: 12 }}>
            🔒 Secured by JusPay · HDFC SmartGateway
          </div>
        </div>
      </div>
    </div>
  );
}
