import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { apiRequest } from '../api/http';
import { API_ROUTES } from '../api/routes';
import { getUserIdFromJwt } from '../api/authSession';
import { getApiBaseRequired } from '../config/apiBase';
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

/* ── SessionStorage key for persisting return context across payment gateway redirect ── */
const PAYMENT_RETURN_CONTEXT_KEY = 'payment_return_context';

type PaymentLocationState = {
  websiteUrl?: string;
  intent?: 'deep-analysis';
  paymentError?: string;
  reason?: string;
  requiredPlanSlug?: string;
  requiredPlanName?: string;
  requiredPlanPrice?: number;
  returnTo?: string;
  returnState?: Record<string, unknown>;
};

type CreateOrderResponse = {
  success?: boolean;
  order_id?: string;
  payment_links?: Record<string, string>;
  error?: string;
  detail?: string;
  message?: string;
};

/** Read & merge location.state with any previously-saved sessionStorage context. */
function resolvePaymentState(locationState: PaymentLocationState): PaymentLocationState {
  let saved: Partial<PaymentLocationState> = {};
  try {
    const raw = sessionStorage.getItem(PAYMENT_RETURN_CONTEXT_KEY);
    if (raw) saved = JSON.parse(raw) as Partial<PaymentLocationState>;
  } catch {
    /* ignore */
  }
  // Location state takes precedence (fresh navigation from agent selector).
  // SessionStorage is the fallback (returning from payment gateway).
  return { ...saved, ...locationState };
}

/** Persist the return context so we can read it after payment gateway redirect. */
function saveReturnContext(state: PaymentLocationState) {
  try {
    const toSave: Partial<PaymentLocationState> = {};
    if (state.returnTo) toSave.returnTo = state.returnTo;
    if (state.returnState) toSave.returnState = state.returnState;
    if (state.intent) toSave.intent = state.intent;
    if (state.websiteUrl) toSave.websiteUrl = state.websiteUrl;
    if (state.reason) toSave.reason = state.reason;
    if (state.requiredPlanSlug) toSave.requiredPlanSlug = state.requiredPlanSlug;
    if (state.requiredPlanName) toSave.requiredPlanName = state.requiredPlanName;
    if (state.requiredPlanPrice) toSave.requiredPlanPrice = state.requiredPlanPrice;
    if (Object.keys(toSave).length > 0) {
      sessionStorage.setItem(PAYMENT_RETURN_CONTEXT_KEY, JSON.stringify(toSave));
    }
  } catch {
    /* ignore */
  }
}

function clearReturnContext() {
  try {
    sessionStorage.removeItem(PAYMENT_RETURN_CONTEXT_KEY);
  } catch {
    /* ignore */
  }
}

function creditsLabel(plan: PlanCatalogRow): string {
  if (plan.credits_allocation == null) return 'Unlimited uses';
  return `${plan.credits_allocation} credits`;
}

/* ── Feature list per plan (shown as bullet checks) ── */
function planFeatures(plan: PlanCatalogRow): string[] {
  const list: string[] = [];
  list.push(creditsLabel(plan));
  if (plan.features?.deep_analysis_report) list.push('Deep analysis report');
  if (plan.features?.execute_report_actions) list.push('Execute report actions');
  return list;
}

export default function PaymentPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const rawState = (location.state || {}) as PaymentLocationState;
  const state = resolvePaymentState(rawState);

  // Persist return context on first render so it survives payment gateway redirect.
  useEffect(() => {
    saveReturnContext(state);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  /** Navigate to the agent new chat after payment success. */
  const navigateAfterPayment = useCallback(() => {
    clearReturnContext();
    try {
      sessionStorage.removeItem(PAYMENT_CONTINUE_WEBSITE_URL_KEY);
    } catch {
      /* ignore */
    }

    // 1. Explicit returnTo (from agent selector / cross-agent action)
    if (state.returnTo) {
      navigate(state.returnTo, { replace: false, state: state.returnState ?? {} });
      return;
    }

    // 2. Deep-analysis intent
    const url = websiteUrlForContinue;
    const userLine = url ? `${url}\n\nDo deep analysis.` : '';
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

    // 3. Fallback: go to new chat
    navigate('/new', { replace: false });
  }, [navigate, state.intent, state.returnTo, state.returnState, websiteUrlForContinue]);

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

  /* ── Handle return from payment gateway (order_id in URL) ── */
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
          // Auto-redirect to agent new chat after successful payment
          navigateAfterPayment();
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
  }, [refreshEntitlements, navigateAfterPayment]);

  const handlePayPlan = async (plan: PlanCatalogRow) => {
    if (!getUserIdFromJwt()) {
      setError('You must be signed in to pay. Complete phone verification from the playbook step.');
      return;
    }
    setPayLoadingSlug(plan.slug);
    setError(null);
    // Persist return context before leaving for external payment gateway
    saveReturnContext(state);
    try {
      // return_url must point to the BACKEND callback — payment gateways POST
      // (not GET) to this URL. The backend converts the POST into a GET redirect
      // to the frontend /payment?order_id=xxx page.
      const returnUrl = `${getApiBaseRequired()}/api/v1/payments/callback`;
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
    if (state.requiredPlanSlug) return state.requiredPlanSlug;
    if (deepAnalysisIntent) return PLAN_SLUG_DEEP_ANALYSIS_L1;
    return plans[0]?.slug;
  }, [deepAnalysisIntent, plans, state.requiredPlanSlug]);

  const hasDeepAnalysis = entitlements != null && canUseDeepAnalysisReport(entitlements);
  const readyBlock =
    !statusLoading && !returnPending && entitlements != null && hasDeepAnalysis;

  const showPlansChrome = !plansLoading && plans.length > 0;
  const showCatalog =
    Boolean(authUserId) && !statusLoading && !returnPending && entitlements != null && showPlansChrome;

  const isLoading = statusLoading || plansLoading || returnPending;

  /* Access-denied reason passed from agent selector / cross-agent action */
  const accessDeniedReason = state.reason;

  return (
    <div className="relative flex min-h-screen flex-col bg-[#0a0118] text-white selection:bg-violet-500/30">
      {/* ── Ambient gradient blobs ── */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-40 h-[600px] w-[600px] rounded-full bg-violet-700/20 blur-[120px]" />
        <div className="absolute -bottom-32 -right-32 h-[500px] w-[500px] rounded-full bg-indigo-600/15 blur-[100px]" />
        <div className="absolute top-1/2 left-1/2 h-[400px] w-[400px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-fuchsia-600/10 blur-[100px]" />
      </div>

      {/* ── Top bar ── */}
      <header className="relative z-10 flex items-center justify-between px-6 py-5 sm:px-10">
        <button
          type="button"
          onClick={() => {
            if (state.returnTo) {
              navigate(state.returnTo, { replace: false, state: state.returnState ?? {} });
              return;
            }
            navigate(-1);
          }}
          className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-medium text-white/80 backdrop-blur-md transition hover:bg-white/[0.08] hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
            <path d="M10 3L5 8l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back
        </button>
        <div className="flex items-center gap-2">
          <div className="h-7 w-7 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center text-xs font-bold shadow-lg shadow-violet-500/20">
            ✦
          </div>
          <span className="text-sm font-semibold tracking-wide text-white/70">Ikshan</span>
        </div>
      </header>

      {/* ── Main content ── */}
      <main className="relative z-10 flex flex-1 flex-col items-center overflow-y-auto px-5 pb-16 pt-4 sm:px-8">
        <div className="w-full max-w-3xl">

          {/* Hero heading */}
          <div className="mb-10 text-center">
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-500/30 to-indigo-500/30 text-2xl shadow-lg shadow-violet-500/10 ring-1 ring-white/10">
              💎
            </div>
            <h1 className="m-0 bg-gradient-to-r from-white via-violet-200 to-indigo-200 bg-clip-text text-3xl font-extrabold tracking-tight text-transparent sm:text-4xl">
              Upgrade Your Plan
            </h1>
            <p className="mx-auto mt-3 max-w-lg text-[15px] leading-relaxed text-white/50">
              Unlock powerful AI capabilities. Choose the plan that fits your needs.
            </p>

            {/* Show access-denied reason if redirected from agent selector */}
            {accessDeniedReason && (
              <div className="mx-auto mt-5 max-w-md rounded-xl border border-amber-500/30 bg-amber-500/10 px-5 py-3 text-sm text-amber-200/90 backdrop-blur-sm">
                {accessDeniedReason}
              </div>
            )}
          </div>

          {/* Loading state */}
          {isLoading && (
            <div className="flex flex-col items-center gap-3 py-12">
              <div className="h-6 w-6 rounded-full border-2 border-violet-400 border-t-transparent animate-spin" />
              <p className="text-sm text-white/40">Loading plans…</p>
            </div>
          )}

          {/* Already-has-access block */}
          {readyBlock && (
            <div className="mx-auto mb-10 max-w-md overflow-hidden rounded-2xl border border-emerald-500/30 bg-emerald-500/[0.06] p-8 text-center backdrop-blur-sm">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-500/20 text-xl">
                ✅
              </div>
              <p className="m-0 mb-6 text-[15px] leading-relaxed text-white/85">
                You already have access! Continue to start using the agent.
              </p>
              <button
                type="button"
                onClick={navigateAfterPayment}
                className="w-full cursor-pointer rounded-xl border-none bg-gradient-to-r from-emerald-500 to-teal-500 py-3.5 text-[15px] font-bold text-white shadow-lg shadow-emerald-500/20 transition hover:shadow-emerald-500/30"
              >
                Continue →
              </button>
            </div>
          )}

          {/* Active grants */}
          {!statusLoading && !returnPending && entitlements != null && entitlements.grants.length > 0 && (
            <div className="mx-auto mb-10 max-w-lg rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6 backdrop-blur-sm">
              <h3 className="m-0 mb-4 flex items-center gap-2 text-sm font-semibold text-white/70">
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500/20 text-[10px]">✓</span>
                Active on your account
              </h3>
              <div className="space-y-2.5">
                {entitlements.grants.map((g) => (
                  <div
                    key={`${g.order_id}-${g.plan_slug}`}
                    className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3"
                  >
                    <div>
                      <span className="text-sm font-semibold text-white/90">{g.plan_name}</span>
                      <span className="mt-0.5 block text-xs text-white/40">
                        {g.credits_unlimited ? 'Unlimited credits' : `${g.credits_remaining ?? 0} credits remaining`}
                      </span>
                    </div>
                    <span className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-emerald-400">
                      Active
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Plan cards */}
          {showCatalog && (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
              {plans.map((plan) => {
                const highlight = plan.slug === defaultHighlightSlug;
                const paying = payLoadingSlug === plan.slug;
                const features = planFeatures(plan);
                return (
                  <div
                    key={plan.slug}
                    className={`relative flex flex-col overflow-hidden rounded-2xl border p-6 backdrop-blur-sm transition-all duration-300 ${
                      highlight
                        ? 'border-violet-400/40 bg-violet-500/[0.06] shadow-lg shadow-violet-500/10 ring-1 ring-violet-400/20'
                        : 'border-white/[0.08] bg-white/[0.03] hover:border-white/[0.14] hover:bg-white/[0.05]'
                    }`}
                  >
                    {/* Recommended badge */}
                    {highlight && (
                      <div className="absolute top-4 right-4">
                        <span className="rounded-full bg-gradient-to-r from-violet-500 to-indigo-500 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-white shadow-md">
                          Recommended
                        </span>
                      </div>
                    )}

                    {/* Plan name + description */}
                    <div className="mb-5">
                      <h2 className="m-0 text-lg font-bold text-white">{plan.name}</h2>
                      <p className="mt-2 text-sm leading-relaxed text-white/50">{plan.description}</p>
                    </div>

                    {/* Price */}
                    <div className="mb-5 flex items-baseline gap-1">
                      <span className="text-4xl font-extrabold tracking-tight text-white">₹{plan.price_inr}</span>
                      <span className="text-sm font-medium text-white/40">one-time</span>
                    </div>

                    {/* Features list */}
                    <ul className="m-0 mb-6 flex-1 list-none space-y-2.5 p-0">
                      {features.map((f, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-sm text-white/65">
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="mt-0.5 shrink-0 text-emerald-400">
                            <path d="M3 8.5l3 3 7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                          {f}
                        </li>
                      ))}
                    </ul>

                    {/* CTA button */}
                    <button
                      type="button"
                      onClick={() => handlePayPlan(plan)}
                      disabled={paying || payLoadingSlug != null}
                      className={`flex w-full cursor-pointer items-center justify-center gap-2 rounded-xl border-none py-3.5 text-sm font-bold text-white shadow-lg transition disabled:cursor-not-allowed disabled:opacity-60 ${
                        highlight
                          ? 'bg-gradient-to-r from-violet-600 to-indigo-600 shadow-violet-500/20 hover:shadow-violet-500/30'
                          : 'bg-white/10 shadow-none hover:bg-white/[0.14]'
                      }`}
                    >
                      {paying ? (
                        <>
                          <div className="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                          Redirecting…
                        </>
                      ) : (
                        <>
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0">
                            <rect x="1" y="4" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="1.4" />
                            <path d="M1 7h14" stroke="currentColor" strokeWidth="1.4" />
                          </svg>
                          Get {plan.name}
                        </>
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* No plans */}
          {authUserId &&
          !statusLoading &&
          !returnPending &&
          entitlements != null &&
          !showPlansChrome &&
          !plansLoading && (
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] px-8 py-12 text-center">
              <p className="text-sm text-white/40">No plans are currently available.</p>
            </div>
          )}

          {/* Not signed in */}
          {!authUserId && !isLoading && (
            <div className="mx-auto max-w-md rounded-2xl border border-amber-500/20 bg-amber-500/[0.06] px-8 py-10 text-center backdrop-blur-sm">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/15 text-xl">
                🔑
              </div>
              <p className="m-0 text-[15px] leading-relaxed text-white/75">
                Sign in with your mobile number to view plans and make a purchase.
              </p>
              <button
                type="button"
                onClick={() => navigate('/', { replace: false })}
                className="mt-6 w-full cursor-pointer rounded-xl border-none bg-white/10 py-3 text-sm font-bold text-white transition hover:bg-white/[0.14]"
              >
                Go to sign in
              </button>
            </div>
          )}
        </div>
      </main>

      {/* ── Error toast ── */}
      {error && (
        <div
          className="fixed bottom-6 left-1/2 z-[200] flex max-w-[90vw] -translate-x-1/2 cursor-pointer items-center gap-3 rounded-xl border border-red-500/30 bg-red-900/90 px-5 py-3.5 text-sm text-white shadow-2xl shadow-red-500/10 backdrop-blur-md animate-[ob-slide-up_0.25s_ease]"
          onClick={() => setError(null)}
          role="alert"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500/30 text-xs">!</span>
          <span className="flex-1">{error}</span>
          <button type="button" className="cursor-pointer border-none bg-transparent p-0 text-lg leading-none text-white/50 hover:text-white/80">
            ×
          </button>
        </div>
      )}
    </div>
  );
}
