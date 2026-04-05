import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getUserIdFromJwt } from '../api/authSession';
import { apiGet } from '../api/http';
import { API_ROUTES } from '../api/routes';
import {
  fetchPlansCatalog,
  fetchPaymentEntitlements,
  type PlanCatalogRow,
  type PlanGrantSummary,
  type UserEntitlements,
} from '../lib/paymentAccess';

type UserProfile = {
  user_id: string;
  email: string | null;
  phone_number: string | null;
  name: string | null;
  provider: string;
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

function creditsDisplay(grant: PlanGrantSummary): string {
  if (grant.credits_unlimited) return 'Unlimited';
  if (grant.credits_remaining === null) return 'Unlimited';
  return `${grant.credits_remaining} remaining`;
}

export default function AccountPage() {
  const navigate = useNavigate();
  const [authUserId, setAuthUserId] = useState<string | null>(null);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [entitlements, setEntitlements] = useState<UserEntitlements | null>(null);
  const [plans, setPlans] = useState<PlanCatalogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    const uid = getUserIdFromJwt();
    setAuthUserId(uid);
    if (!uid) {
      setLoading(false);
      return;
    }
    try {
      const [ent, planList, meResponse] = await Promise.all([
        fetchPaymentEntitlements(),
        fetchPlansCatalog(),
        apiGet<{ authenticated: boolean; user: UserProfile }>(API_ROUTES.auth.me),
      ]);
      setEntitlements(ent);
      setPlans(planList);
      if (meResponse.authenticated && meResponse.user) {
        setUserProfile(meResponse.user);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load account data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const activeGrants = entitlements?.grants ?? [];
  const hasActivePlan = activeGrants.length > 0;

  // Find plans user doesn't have yet (for upgrade suggestions)
  const ownedSlugs = new Set(activeGrants.map((g) => g.plan_slug));
  const availableUpgrades = plans.filter((p) => !ownedSlugs.has(p.slug));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading account…</span>
        </div>
      </div>
    );
  }

  if (!authUserId) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-6 text-center">
        <div className="w-16 h-16 bg-amber-500/20 rounded-2xl flex items-center justify-center text-3xl mb-5">
          🔑
        </div>
        <h2 className="text-xl font-bold text-slate-100 mb-2">Sign in required</h2>
        <p className="text-sm text-slate-400 mb-6 max-w-md">
          Sign in with your mobile number to view your account and subscription details.
        </p>
        <button
          type="button"
          onClick={() => navigate('/')}
          className="px-6 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-semibold hover:bg-violet-500 transition"
        >
          Go to Sign In
        </button>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-10">
        {/* Header */}
        <div className="mb-10">
          <h1 className="text-2xl font-bold text-slate-100 mb-2">Account & Subscription</h1>
          <p className="text-sm text-slate-400">
            Manage your plans, view credits, and explore upgrades.
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Profile Information */}
        <section className="mb-10">
          <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
            <span className="w-6 h-6 bg-blue-500/20 rounded-lg flex items-center justify-center text-xs">👤</span>
            Profile Information
          </h2>

          <div className="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5">
            <div className="space-y-4">
              {/* Phone Number */}
              <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-slate-800 rounded-xl flex items-center justify-center text-lg">
                    📱
                  </div>
                  <div>
                    <p className="text-xs text-slate-500 uppercase tracking-wide">Phone Number</p>
                    <p className={`text-sm font-medium ${userProfile?.phone_number ? 'text-slate-200' : 'text-slate-500 italic'}`}>
                      {userProfile?.phone_number 
                        ? `+91 ${userProfile.phone_number.replace(/^91/, '').replace(/(\d{5})(\d{5})/, '$1 $2')}`
                        : 'Not Set'}
                    </p>
                  </div>
                </div>
                {!userProfile?.phone_number && (
                  <button
                    type="button"
                    onClick={() => navigate('/phone-verify?mode=link')}
                    className="px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-500 transition"
                  >
                    Add Phone
                  </button>
                )}
                {userProfile?.phone_number && (
                  <span className="px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                    Verified
                  </span>
                )}
              </div>

              {/* Email */}
              <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-slate-800 rounded-xl flex items-center justify-center text-lg">
                    ✉️
                  </div>
                  <div>
                    <p className="text-xs text-slate-500 uppercase tracking-wide">Email</p>
                    <p className={`text-sm font-medium ${userProfile?.email ? 'text-slate-200' : 'text-slate-500 italic'}`}>
                      {userProfile?.email || 'Not Set'}
                    </p>
                  </div>
                </div>
                {!userProfile?.email && (
                  <button
                    type="button"
                    onClick={() => navigate('/google-login?mode=link')}
                    className="px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-500 transition flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24">
                      <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                      <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                    </svg>
                    Link Google
                  </button>
                )}
                {userProfile?.email && (
                  <span className="px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                    Verified
                  </span>
                )}
              </div>

              {/* Name (if available) */}
              {userProfile?.name && (
                <div className="flex items-center justify-between py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 bg-slate-800 rounded-xl flex items-center justify-center text-lg">
                      🏷️
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wide">Name</p>
                      <p className="text-sm font-medium text-slate-200">
                        {userProfile.name}
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Admin Grant Notice */}
        {entitlements?.has_admin_grant && entitlements.admin_grant && (
          <section className="mb-10">
            <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 bg-emerald-500/20 rounded-xl flex items-center justify-center text-2xl shrink-0">
                  🎫
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-bold text-emerald-200 mb-1">
                    Admin-Granted Full Access
                  </h3>
                  <p className="text-sm text-emerald-300/80 mb-2">
                    You have been granted full subscription access by an administrator. All features are unlocked.
                  </p>
                  <div className="flex flex-wrap gap-4 text-xs text-emerald-300/70">
                    <div>
                      <span className="text-emerald-400/50">Granted by:</span>{' '}
                      <span className="text-emerald-200 font-medium">
                        {entitlements.admin_grant.granted_by_email || 'Admin'}
                      </span>
                    </div>
                    <div>
                      <span className="text-emerald-400/50">Since:</span>{' '}
                      <span className="text-emerald-200 font-medium">
                        {formatDate(entitlements.admin_grant.granted_at)}
                      </span>
                    </div>
                    {entitlements.admin_grant.reason && (
                      <div>
                        <span className="text-emerald-400/50">Reason:</span>{' '}
                        <span className="text-emerald-200 font-medium">
                          {entitlements.admin_grant.reason}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Active Plans */}
        <section className="mb-10">
          <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
            <span className="w-6 h-6 bg-emerald-500/20 rounded-lg flex items-center justify-center text-xs">✓</span>
            Active Plans
          </h2>

          {!hasActivePlan ? (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-8 text-center">
              <div className="w-14 h-14 bg-slate-800 rounded-2xl flex items-center justify-center text-2xl mx-auto mb-4">
                📦
              </div>
              <p className="text-slate-400 text-sm mb-4">
                You don't have any active plans yet.
              </p>
              <button
                type="button"
                onClick={() => navigate('/payment')}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 text-white text-sm font-semibold hover:shadow-lg hover:shadow-violet-500/20 transition"
              >
                <span>💎</span>
                Browse Plans
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              {activeGrants.map((grant) => {
                const planDef = plans.find((p) => p.slug === grant.plan_slug);
                const isAdminGrant = grant.is_admin_grant === true;
                return (
                  <div
                    key={`${grant.order_id}-${grant.plan_slug}`}
                    className={`rounded-2xl border ${isAdminGrant ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-slate-700/60 bg-slate-900/60'} p-5`}
                  >
                    <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                      {/* Plan info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <h3 className="text-base font-bold text-slate-100">{grant.plan_name}</h3>
                          {isAdminGrant ? (
                            <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                              Admin Granted
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 text-[10px] font-bold uppercase tracking-wider">
                              Active
                            </span>
                          )}
                        </div>
                        {planDef?.description && (
                          <p className="text-sm text-slate-400 mb-3">{planDef.description}</p>
                        )}
                        {isAdminGrant && grant.granted_by_email && (
                          <p className="text-sm text-emerald-300/70 mb-3">
                            Granted by: {grant.granted_by_email}
                          </p>
                        )}
                        <div className="flex flex-wrap gap-4 text-xs text-slate-400">
                          <div>
                            <span className="text-slate-500">Credits:</span>{' '}
                            <span className="text-slate-200 font-medium">{creditsDisplay(grant)}</span>
                          </div>
                          <div>
                            <span className="text-slate-500">{isAdminGrant ? 'Granted:' : 'Purchased:'}</span>{' '}
                            <span className="text-slate-200 font-medium">{formatDate(grant.granted_at)}</span>
                          </div>
                          {!isAdminGrant && (
                            <div>
                              <span className="text-slate-500">Order:</span>{' '}
                              <span className="text-slate-300 font-mono text-[11px]">{grant.order_id}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Actions */}
                      {!isAdminGrant && (
                        <div className="flex flex-col gap-2 sm:items-end shrink-0">
                          {/* For now, cancel is a placeholder — could link to support */}
                          <button
                            type="button"
                            onClick={() => {
                              // TODO: Implement cancel flow (contact support or API)
                              alert('To cancel your plan, please contact support at support@ikshan.in');
                            }}
                            className="px-4 py-2 rounded-lg border border-slate-600 text-slate-300 text-xs font-medium hover:bg-slate-800 transition"
                          >
                            Cancel Plan
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Features */}
                    {grant.features && Object.keys(grant.features).length > 0 && (
                      <div className="mt-4 pt-4 border-t border-slate-800">
                        <p className="text-xs text-slate-500 mb-2">Included features:</p>
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(grant.features).map(([key, val]) =>
                            val ? (
                              <span
                                key={key}
                                className="px-2.5 py-1 rounded-lg bg-violet-500/10 text-violet-300 text-xs"
                              >
                                {key.replace(/_/g, ' ')}
                              </span>
                            ) : null
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Upgrade Options */}
        {availableUpgrades.length > 0 && (
          <section className="mb-10">
            <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
              <span className="w-6 h-6 bg-violet-500/20 rounded-lg flex items-center justify-center text-xs">⬆</span>
              Upgrade Options
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {availableUpgrades.map((plan) => (
                <div
                  key={plan.slug}
                  className="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5 hover:border-violet-500/40 transition"
                >
                  <h3 className="text-base font-bold text-slate-100 mb-1">{plan.name}</h3>
                  <p className="text-sm text-slate-400 mb-3 line-clamp-2">{plan.description}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-xl font-bold text-slate-100">₹{plan.price_inr}</span>
                    <button
                      type="button"
                      onClick={() =>
                        navigate('/payment', {
                          state: { requiredPlanSlug: plan.slug },
                        })
                      }
                      className="px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-semibold hover:bg-violet-500 transition"
                    >
                      Upgrade
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Capabilities Summary */}
        {entitlements?.capabilities && Object.keys(entitlements.capabilities).length > 0 && (
          <section className="mb-10">
            <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
              <span className="w-6 h-6 bg-indigo-500/20 rounded-lg flex items-center justify-center text-xs">🔓</span>
              Your Capabilities
            </h2>

            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/60 p-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {Object.entries(entitlements.capabilities).map(([key, cap]) => (
                  <div
                    key={key}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl ${
                      cap.allowed
                        ? 'bg-emerald-500/10 border border-emerald-500/20'
                        : 'bg-slate-800/50 border border-slate-700/50'
                    }`}
                  >
                    <span className={`text-lg ${cap.allowed ? 'text-emerald-400' : 'text-slate-500'}`}>
                      {cap.allowed ? '✓' : '✗'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium ${cap.allowed ? 'text-emerald-200' : 'text-slate-400'}`}>
                        {key.replace(/_/g, ' ')}
                      </p>
                      {cap.allowed && (
                        <p className="text-xs text-slate-400">
                          {cap.unlimited
                            ? 'Unlimited'
                            : cap.credits_remaining !== null
                            ? `${cap.credits_remaining} credits`
                            : 'Active'}
                        </p>
                      )}
                    </div>
                    {!cap.allowed && (
                      <button
                        type="button"
                        onClick={() => navigate('/payment')}
                        className="px-3 py-1.5 rounded-lg bg-violet-600/80 text-white text-[11px] font-semibold hover:bg-violet-500 transition"
                      >
                        Unlock
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* Quick Actions */}
        <section>
          <h2 className="text-lg font-semibold text-slate-200 mb-4 flex items-center gap-2">
            <span className="w-6 h-6 bg-slate-700 rounded-lg flex items-center justify-center text-xs">⚡</span>
            Quick Actions
          </h2>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => navigate('/payment')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-800 transition"
            >
              💎 Browse All Plans
            </button>
            <button
              type="button"
              onClick={() => navigate('/new')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-800 transition"
            >
              ✨ Start New Chat
            </button>
            <button
              type="button"
              onClick={() => navigate('/conversations')}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl border border-slate-700 text-slate-200 text-sm font-medium hover:bg-slate-800 transition"
            >
              🕒 View History
            </button>
          </div>
        </section>

        {/* Support */}
        <div className="mt-12 pt-8 border-t border-slate-800 text-center">
          <p className="text-xs text-slate-500">
            Need help? Contact us at{' '}
            <a href="mailto:support@ikshan.in" className="text-violet-400 hover:underline">
              support@ikshan.in
            </a>
          </p>
        </div>
      </div>
    </div>
  );
}

