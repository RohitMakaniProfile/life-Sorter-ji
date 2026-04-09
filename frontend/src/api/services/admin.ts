import { API_ROUTES } from '../routes';
import { apiGet, apiPost, apiRequest } from '../http';
import type {
  ObservabilitySnapshot,
  SystemConfigEntry,
  ConfigValueType,
  AdminSubscriptionGrant,
  AdminSubscriptionGrantAuditLog,
  AdminSubscriptionUserSearchResult,
  AdminUsersResponse,
  AdminSkillCallSummary,
  AdminSkillCallDetail,
  PromptEntry,
  AdminTokenUsageSummary,
  AdminTokenUsageUser,
  AdminTokenUsageConversation,
  AdminTokenUsageCall,
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
  body: { value: string; type?: ConfigValueType; description: string },
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

export async function listUserSkillCalls(
  userId: string,
  limit?: number,
  offset?: number,
): Promise<{ calls: AdminSkillCallSummary[]; total: number; limit: number; offset: number }> {
  return apiGet(API_ROUTES.admin.management.userSkillCalls(userId, limit, offset));
}

export async function getSkillCallDetail(
  skillCallId: string,
): Promise<{ call: AdminSkillCallDetail }> {
  return apiGet(API_ROUTES.admin.management.skillCallDetail(skillCallId));
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

// Prompts API
export async function listPrompts(category?: string): Promise<{ prompts: PromptEntry[] }> {
  const url = category
    ? `${API_ROUTES.admin.management.prompts}?category=${encodeURIComponent(category)}`
    : API_ROUTES.admin.management.prompts;
  return apiGet<{ prompts: PromptEntry[] }>(url);
}

export async function getTokenUsageSummary(): Promise<AdminTokenUsageSummary> {
  return apiGet<AdminTokenUsageSummary>(API_ROUTES.admin.management.tokenUsageSummary);
}

export async function getTokenUsageUsers(q?: string, limit?: number, offset?: number): Promise<{ users: AdminTokenUsageUser[]; limit: number; offset: number }> {
  return apiGet<{ users: AdminTokenUsageUser[]; limit: number; offset: number }>(
    API_ROUTES.admin.management.tokenUsageUsers(q, limit, offset),
  );
}

export async function getTokenUsageUserConversations(userId: string, limit?: number, offset?: number): Promise<{ conversations: AdminTokenUsageConversation[]; limit: number; offset: number }> {
  return apiGet<{ conversations: AdminTokenUsageConversation[]; limit: number; offset: number }>(
    API_ROUTES.admin.management.tokenUsageUserConversations(userId, limit, offset),
  );
}

export async function getTokenUsageConversationCalls(conversationId: string, limit?: number, offset?: number): Promise<{ calls: AdminTokenUsageCall[]; limit: number; offset: number }> {
  return apiGet<{ calls: AdminTokenUsageCall[]; limit: number; offset: number }>(
    API_ROUTES.admin.management.tokenUsageConversationCalls(conversationId, limit, offset),
  );
}

export async function getPrompt(slug: string): Promise<{ prompt: PromptEntry }> {
  return apiGet<{ prompt: PromptEntry }>(API_ROUTES.admin.management.promptBySlug(slug));
}

export async function upsertPrompt(
  slug: string,
  body: { name: string; content: string; description: string; category: string },
): Promise<{ prompt: PromptEntry }> {
  const res = await apiRequest(API_ROUTES.admin.management.promptBySlug(slug), {
    method: 'PUT',
    headers: new Headers({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any)?.detail || (detail as any)?.message || `Request failed: ${res.status}`);
  }
  return (await res.json()) as { prompt: PromptEntry };
}

export async function deletePrompt(slug: string): Promise<{ deleted: boolean; slug: string }> {
  const res = await apiRequest(API_ROUTES.admin.management.promptBySlug(slug), {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any)?.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

