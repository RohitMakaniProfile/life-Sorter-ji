import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '../../../api/http';
import { API_ROUTES } from '../../../api/routes';
import { getUserIdFromJwt } from '../../../api/authSession';
import { PAYMENT_CONTINUE_WEBSITE_URL_KEY, canUseDeepAnalysisReport } from '../../../lib/paymentAccess';

/**
 * Hook to handle deep analysis navigation and payment flow
 */
export function useDeepAnalysis({ getWebsiteUrl, setError }) {
  const navigate = useNavigate();

  const handleDeepAnalysis = useCallback(async () => {
    const url = getWebsiteUrl();
    try {
      if (url) sessionStorage.setItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY, url);
      else sessionStorage.removeItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY);
    } catch {
      // ignore
    }

    if (!getUserIdFromJwt()) {
      setError('Verify your mobile number (playbook unlock step) before deep analysis.');
      return;
    }

    try {
      const ent = await apiGet(API_ROUTES.payments.entitlements);
      if (canUseDeepAnalysisReport(ent)) {
        const userLine = url ? `${url}\n\nDo deep analysis.` : '';
        navigate('/new', {
          state: {
            agentId: 'business-research',
            ...(userLine ? { initialMessage: userLine } : {}),
          },
        });
        return;
      }
    } catch (err) {
      setError(err?.message || 'Could not load plan entitlements.');
      return;
    }

    navigate('/payment', { state: { intent: 'deep-analysis', websiteUrl: url || undefined } });
  }, [getWebsiteUrl, setError, navigate]);

  return { handleDeepAnalysis };
}

