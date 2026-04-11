import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiPost } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { getUserIdFromJwt } from '../../../api/authSession';

/**
 * Handles JusPay payment return redirect.
 * When user returns from payment gateway with order_id in URL,
 * confirms payment and redirects to payment page.
 */
export function usePaymentRedirect() {
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '');
    const orderId = params.get('order_id');
    if (!orderId) return;

    const uid = getUserIdFromJwt();

    const stripPaymentQuery = () => {
      try {
        window.history.replaceState({}, '', window.location.pathname);
      } catch {
        /* ignore */
      }
    };

    (async () => {
      if (!uid) {
        stripPaymentQuery();
        if (!cancelled) {
          navigate('/payment', {
            replace: true,
            state: {
              paymentError: 'Sign in with your mobile number to finish confirming payment.',
            },
          });
        }
        return;
      }
      try {
        await apiPost(API_ROUTES.payments.complete, { order_id: orderId });
        stripPaymentQuery();
        if (!cancelled) navigate('/payment', { replace: true });
      } catch (err) {
        stripPaymentQuery();
        const msg = err?.message || 'Could not confirm payment.';
        if (!cancelled) navigate('/payment', { replace: true, state: { paymentError: msg } });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [navigate]);
}

