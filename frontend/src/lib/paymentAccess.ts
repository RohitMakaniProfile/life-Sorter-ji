import { apiGet, apiPost } from '../api/http';
import { API_ROUTES } from '../api/routes';

/** Preserved when leaving for JusPay so return to `/` still knows post-pay navigation (e.g. deep analysis). */
export const PAYMENT_CONTINUE_WEBSITE_URL_KEY = 'payment-continue-website-url';

/** Catalog slug: deep analysis / research agent (compute). */
export const PLAN_SLUG_DEEP_ANALYSIS_L1 = 'deep_analysis_l1';

/** Catalog slug: execute action items on reports (future). */
export const PLAN_SLUG_REPORT_ACTIONS_L2 = 'report_actions_l2';

export type CapabilityState = {
  allowed: boolean;
  unlimited?: boolean;
  credits_remaining?: number | null;
  via_admin_grant?: boolean;
};

export type PlanGrantSummary = {
  plan_slug: string;
  plan_name: string;
  order_id: string;
  credits_remaining: number | null;
  credits_unlimited: boolean;
  granted_at?: string | null;
  features: Record<string, unknown>;
  // Admin grant specific fields
  is_admin_grant?: boolean;
  granted_by_email?: string;
};

export type AdminGrantInfo = {
  id: string;
  user_id: string;
  granted_by_user_id: string;
  granted_by_email: string;
  reason: string;
  is_active: boolean;
  granted_at?: string | null;
};

export type UserEntitlements = {
  user_id: string;
  grants: PlanGrantSummary[];
  capabilities: Record<string, CapabilityState>;
  has_admin_grant?: boolean;
  admin_grant?: AdminGrantInfo | null;
};

export type PlanCatalogRow = {
  id: string;
  slug: string;
  name: string;
  description: string;
  price_inr: number;
  credits_allocation: number | null;
  features: Record<string, unknown>;
  display_order: number;
};

export async function fetchPlansCatalog(): Promise<PlanCatalogRow[]> {
  return apiGet<PlanCatalogRow[]>(API_ROUTES.plans.list);
}

/** Requires `Authorization: Bearer` (OTP / auth JWT). */
export async function fetchPaymentEntitlements(): Promise<UserEntitlements> {
  return apiGet<UserEntitlements>(API_ROUTES.payments.entitlements);
}

export function canUseDeepAnalysisReport(ent: UserEntitlements | null | undefined): boolean {
  return Boolean(ent?.capabilities?.deep_analysis_report?.allowed);
}

export function canExecuteReportActions(ent: UserEntitlements | null | undefined): boolean {
  return Boolean(ent?.capabilities?.execute_report_actions?.allowed);
}

/** Requires JWT; `order_id` from JusPay return URL. */
export async function completePlanCheckout(orderId: string): Promise<void> {
  await apiPost<{ success?: boolean }>(API_ROUTES.payments.complete, {
    order_id: orderId,
  });
}
