import { API_ROUTES } from '../routes';
import { apiGet, apiPost, apiRequest } from '../http';
import type {
  ObservabilitySnapshot,
  SystemConfigEntry,
  AdminSubscriptionGrant,
  AdminSubscriptionGrantAuditLog,
  AdminSubscriptionUserSearchResult,
  AdminUsersResponse,
} from '../types';

export async function getObservabilitySnapshot(): Promise<ObservabilitySnapshot> {
  return apiGet<ObservabilitySnapshot>(API_ROUTES.admin.management.observability);
}

export async function listSystemConfig(): Promise<{ entries: SystemConfigEntry[] }> {
  return apiGet<{ entries: SystemConfigEntry[] }>(API_ROUTES.admin.management.config);
}

export async function getSystemConfigEntry(
  key: string,
): Promise<{ entry: SystemConfigEntry }> {
  return apiGet<{ entry: SystemConfigEntry }>(API_ROUTES.admin.management.configByKey(key));
}

export async function upsertSystemConfigEntry(
  key: string,
  body: { value: string; description: string },
): Promise<{ entry: SystemConfigEntry }> {
  const res = await apiRequest(API_ROUTES.admin.management.configByKey(key), {
    method: 'PATCH',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any)?.detail || (detail as any)?.message || `Request failed: ${res.status}`);
  }
  return (await res.json()) as { entry: SystemConfigEntry };
}

// Admin Users API
export async function listAdminUsers(
  q?: string,
  limit?: number,
  offset?: number,
): Promise<AdminUsersResponse> {
  return apiGet<AdminUsersResponse>(API_ROUTES.admin.management.users(q, limit, offset));
}

export async function deleteAdminUser(
  userId: string,
): Promise<{ success: boolean; deleted_user_id: string; deleted_email: string; deleted_phone: string }> {
  const res = await apiRequest(API_ROUTES.admin.management.deleteUser(userId), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any)?.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

// Admin Subscription Grants API
export async function listAdminSubscriptionGrants(): Promise<{ grants: AdminSubscriptionGrant[] }> {
  return apiGet<{ grants: AdminSubscriptionGrant[] }>(API_ROUTES.admin.subscriptionGrants.list);
}

export async function getAdminSubscriptionGrantAuditLog(
  userId?: string,
): Promise<{ logs: AdminSubscriptionGrantAuditLog[] }> {
  const url = userId
    ? `${API_ROUTES.admin.subscriptionGrants.auditLog}?user_id=${encodeURIComponent(userId)}`
    : API_ROUTES.admin.subscriptionGrants.auditLog;
  return apiGet<{ logs: AdminSubscriptionGrantAuditLog[] }>(url);
}

export async function searchUsersForGrant(
  query: string,
): Promise<{ users: AdminSubscriptionUserSearchResult[] }> {
  return apiGet<{ users: AdminSubscriptionUserSearchResult[] }>(
    API_ROUTES.admin.subscriptionGrants.searchUsers(query),
  );
}

export async function grantAdminSubscription(
  userId: string,
  reason: string = '',
): Promise<{ success: boolean; user_id: string; user_email: string; user_phone: string }> {
  return apiPost<{ success: boolean; user_id: string; user_email: string; user_phone: string }>(
    API_ROUTES.admin.subscriptionGrants.grant,
    { user_id: userId, reason },
  );
}

export async function revokeAdminSubscription(
  userId: string,
  reason: string = '',
): Promise<{ success: boolean; user_id: string }> {
  return apiPost<{ success: boolean; user_id: string }>(
    API_ROUTES.admin.subscriptionGrants.revoke,
    { user_id: userId, reason },
  );
}

