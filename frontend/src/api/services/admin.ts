import { API_ROUTES } from '../routes';
import { apiGet, apiPost, apiRequest } from '../http';
import type { ObservabilitySnapshot, SystemConfigEntry } from '../types';

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

