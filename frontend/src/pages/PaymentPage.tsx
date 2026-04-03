import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, CreditCard } from 'lucide-react';
import StageLayout from '../components/onboarding/components/StageLayout';
import { apiRequest } from '../api/http';
import { API_ROUTES } from '../api/routes';
import { getUserIdFromJwt } from '../api/authSession';
import {
  PLAN_SLUG_DEEP_ANALYSIS_L1,
  PAYMENT_CONTINUE_WEBSITE_URL_KEY,
  canUseDeepAnalysisReport,
  completePlanCheckout,
  fetchPlansCatalog,
  fetchPaymentEntitlements,
  type PlanCatalogRow,
  type UserEntitlements,
} from '../lib/paymentAccess';

const RESEARCH_ORCHESTRATOR_AGENT_ID = 'business-research';

type PaymentLocationState = {
  websiteUrl?: string;
  intent?: 'deep-analysis';
  paymentError?: string;
};

type CreateOrderResponse = {
  success?: boolean;
  order_id?: string;
  payment_links?: Record<string, string>;
  error?: string;
  detail?: string;
  message?: string;
};

function creditsLabel(plan: PlanCatalogRow): string {
  if (plan.credits_allocation == null) return 'Unlimited uses (this purchase)';
  return `${plan.credits_allocation} credits`;
}

export default function PaymentPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state || {}) as PaymentLocationState;

  const websiteUrlForContinue =
    (state.websiteUrl || '').trim() ||
    (typeof window !== 'undefined'
      ? (() => {
          try {
            return (sessionStorage.getItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY) || '').trim();
          } catch {
            return '';
          }
        })()
      : '');

  const [authUserId, setAuthUserId] = useState<string | null>(() =>
    typeof window !== 'undefined' ? getUserIdFromJwt() : null,
  );
  const [entitlements, setEntitlements] = useState<UserEntitlements | null>(null);
  const [plans, setPlans] = useState<PlanCatalogRow[]>([]);
  const [statusLoading, setStatusLoading] = useState(true);
  const [plansLoading, setPlansLoading] = useState(true);
  const [payLoadingSlug, setPayLoadingSlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(state.paymentError ?? null);
  const [returnPending, setReturnPending] = useState(() => {
    if (typeof window === 'undefined') return false;
    return Boolean(new URLSearchParams(window.location.search).get('order_id'));
  });

  const refreshEntitlements = useCallback(async () => {
    const e = await fetchPaymentEntitlements();
    setEntitlements(e);
    return e;
  }, []);

  useEffect(() => {
    const uid = getUserIdFromJwt();
    setAuthUserId(uid);
    if (!uid) {
      setStatusLoading(false);
      setPlansLoading(false);
      setError((prev) => prev ?? 'Sign in with your mobile number (playbook unlock step) to view plans and pay.');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        await refreshEntitlements();
      } catch {
        if (!cancelled) setError('Could not load entitlements. Try signing in again.');
      } finally {
        if (!cancelled) setStatusLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshEntitlements]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await fetchPlansCatalog();
        if (!cancelled) setPlans(list);
      } catch {
        if (!cancelled) setError((prev) => prev ?? 'Could not load plans.');
      } finally {
        if (!cancelled) setPlansLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const orderId = params.get('order_id');
    const uid = getUserIdFromJwt();
    if (!orderId) {
      setReturnPending(false);
      return;
    }
    if (!uid) {
      setReturnPending(false);
      setError('Sign in with the same account you used to start checkout to confirm payment.');
      return;
    }
    let cancelled = false;
    (async () => {
      const stripQuery = () => {
        try {
          window.history.replaceState({}, '', window.location.pathname);
        } catch {
          /* ignore */
        }
      };
      try {
        await completePlanCheckout(orderId);
        stripQuery();
        if (!cancelled) {
          await refreshEntitlements();
          setError(null);
        }
      } catch (e) {
        stripQuery();
        const msg = e instanceof Error ? e.message : 'Could not confirm payment.';
        if (!cancelled) setError(msg);
      } finally {
        if (!cancelled) setReturnPending(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshEntitlements]);

  const continueAfterPay = useCallback(() => {
    const url = websiteUrlForContinue;
    const userLine = url ? `${url}\n\nDo deep analysis.` : '';
    try {
      sessionStorage.removeItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY);
    } catch {
      // ignore
    }
    if (state.intent === 'deep-analysis') {
      navigate('/new', {
        replace: false,
        state: {
          agentId: RESEARCH_ORCHESTRATOR_AGENT_ID,
          ...(userLine ? { initialMessage: userLine } : {}),
        },
      });
      return;
    }
    navigate('/', { replace: false });
  }, [navigate, state.intent, websiteUrlForContinue]);

  const handlePayPlan = async (plan: PlanCatalogRow) => {
    if (!getUserIdFromJwt()) {
      setError('You must be signed in to pay. Complete phone verification from the playbook step.');
      return;
    }
    setPayLoadingSlug(plan.slug);
    setError(null);
    try {
      const returnUrl = `${window.location.origin}/payment`;
      const res = await apiRequest(API_ROUTES.payments.createOrder, {
        method: 'POST',
        body: JSON.stringify({
          amount: 0,
          return_url: returnUrl,
          plan_slug: plan.slug,
        }),
      });
      const data = (await res.json()) as CreateOrderResponse;
      if (!res.ok) {
        throw new Error(data.detail || data.message || data.error || 'Failed to create payment order');
      }
      if (data.success && data.payment_links) {
        const paymentUrl =
          data.payment_links.web || data.payment_links.mobile || Object.values(data.payment_links)[0];
        if (paymentUrl) {
          window.location.href = paymentUrl;
          return;
        }
        throw new Error('No payment URL received');
      }
      throw new Error(data.error || 'Failed to create payment order');
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Payment failed';
      setError(msg);
    } finally {
      setPayLoadingSlug(null);
    }
  };

  const deepAnalysisIntent = state.intent === 'deep-analysis';

  const defaultHighlightSlug = useMemo(() => {
    if (deepAnalysisIntent) return PLAN_SLUG_DEEP_ANALYSIS_L1;
    return plans[0]?.slug;
  }, [deepAnalysisIntent, plans]);

  const hasDeepAnalysis = entitlements != null && canUseDeepAnalysisReport(entitlements);
  const readyBlock =
    !statusLoading && !returnPending && entitlements != null && deepAnalysisIntent && hasDeepAnalysis;

  const showPlansChrome = !plansLoading && plans.length > 0;
  const showCatalog =
    Boolean(authUserId) && !statusLoading && !returnPending && entitlements != null && showPlansChrome;

  return (
    <StageLayout error={error} onClearError={() => setError(null)}>
      <div className="flex min-h-0 flex-1 flex-col overflow-auto px-6 py-8">
        <div className="mx-auto w-full max-w-[52rem]">
          <button
            type="button"
            onClick={() => navigate('/', { replace: false })}
            className="mb-6 inline-flex cursor-pointer items-center gap-2 rounded-lg border border-white/15 bg-white/[0.06] px-3 py-2 text-sm font-semibold text-white/90 transition hover:bg-white/[0.1]"
          >
            <ArrowLeft size={16} />
            Back
          </button>

          <h1 className="m-0 mb-2 text-center text-[clamp(20px,2.5vw,28px)] font-extrabold text-white">Plans &amp; payment</h1>
          <p className="mx-auto mb-8 max-w-xl text-center text-sm leading-relaxed text-white/55">
            Choose a plan. Payment is tied to your signed-in account (mobile OTP). Deep analysis uses compute;
            report actions are a separate upgrade for a future workflow.
          </p>

          {!authUserId ? null : statusLoading || returnPending ? (
            <p className="text-center text-sm text-white/50">Loading…</p>
          ) : null}

          {readyBlock ? (
            <div className="mx-auto mb-8 max-w-md rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-6 py-8 text-center">
              <p className="m-0 mb-6 text-[15px] leading-relaxed text-white/90">
                Your account has deep analysis access. Continue to the research assistant.
              </p>
              <button
                type="button"
                onClick={continueAfterPay}
                className="w-full cursor-pointer rounded-[10px] border-none bg-gradient-to-br from-indigo-500 to-violet-500 py-3 text-[15px] font-bold text-white"
              >
                Continue to deep analysis →
              </button>
            </div>
          ) : null}

          {!statusLoading && !returnPending && entitlements != null && entitlements.grants.length > 0 ? (
            <div className="mx-auto mb-8 max-w-lg rounded-2xl border border-white/12 bg-white/[0.04] px-6 py-6 text-white/90">
              <p className="m-0 mb-4 text-center text-[15px] font-semibold">Active on your account</p>
              <ul className="m-0 list-none space-y-3 p-0 text-sm text-white/75">
                {entitlements.grants.map((g) => (
                  <li
                    key={`${g.order_id}-${g.plan_slug}`}
                    className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2"
                  >
                    <span className="font-bold text-white/90">{g.plan_name}</span>
                    <span className="block text-xs text-white/50">
                      {g.credits_unlimited ? 'Unlimited credits' : `${g.credits_remaining ?? 0} credits left`}
                    </span>
                  </li>
                ))}
              </ul>
              {!deepAnalysisIntent ? (
                <button
                  type="button"
                  onClick={() => navigate('/', { replace: false })}
                  className="mt-6 w-full cursor-pointer rounded-[10px] border-none bg-white/10 py-3 text-[14px] font-bold text-white"
                >
                  Back to onboarding
                </button>
              ) : null}
            </div>
          ) : null}

          {showCatalog ? (
            <div className="mt-2 flex flex-col gap-5">
              {plans.map((plan) => {
                const highlight = plan.slug === defaultHighlightSlug;
                const paying = payLoadingSlug === plan.slug;
                return (
                  <div
                    key={plan.slug}
                    className={`rounded-2xl border p-5 transition-colors ${
                      highlight
                        ? 'border-violet-400/50 bg-violet-500/[0.08]'
                        : 'border-white/12 bg-white/[0.03]'
                    }`}
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0 flex-1">
                        <h2 className="m-0 text-lg font-extrabold text-white">{plan.name}</h2>
                        <p className="mt-2 text-sm leading-relaxed text-white/60">{plan.description}</p>
                        <p className="mt-2 text-xs text-emerald-300/90">{creditsLabel(plan)}</p>
                        {plan.features?.deep_analysis_report ? (
                          <p className="mt-1 text-xs text-white/40">Includes: deep analysis report</p>
                        ) : null}
                        {plan.features?.execute_report_actions ? (
                          <p className="mt-1 text-xs text-white/40">Includes: execute report actions (future)</p>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 flex-col items-stretch gap-2 sm:w-44 sm:items-end">
                        <span className="text-2xl font-extrabold text-white">₹{plan.price_inr}</span>
                        <button
                          type="button"
                          onClick={() => handlePayPlan(plan)}
                          disabled={paying || payLoadingSlug != null}
                          className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border-none bg-gradient-to-br from-emerald-600 to-emerald-500 px-4 py-2.5 text-sm font-bold text-white shadow-lg disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <CreditCard size={16} />
                          {paying ? 'Redirecting…' : 'Pay'}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}

          {authUserId &&
          !statusLoading &&
          !returnPending &&
          entitlements != null &&
          !showPlansChrome &&
          !plansLoading ? (
            <p className="text-center text-sm text-white/50">No plans are configured.</p>
          ) : null}
        </div>
      </div>
    </StageLayout>
  );
}
