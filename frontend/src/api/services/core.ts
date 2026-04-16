import { API_ROUTES } from '../routes';
import { apiPost, apiRequest } from '../http';
import { getUserIdFromJwt } from '../authSession';
import { getApiBaseRequired } from '../../config/apiBase';
import type {
  AgentId,
  ChatMessage,
  ConversationSummary,
  PlaybookHistoryItem,
  PlaybookRunDetail,
  PipelineStage,
  ProgressEvent,
  SendMessageStreamOptions,
  SkillCallFull,
  SkillMeta,
  StreamCallbacks,
  StreamResult,
  TokenUsage,
  UiAgent,
  Product,
} from '../types';

/** Onboarding helpers + raw `request` for non-JSON flows (e.g. CSV fetch). */
export const coreApi = {
  onboardingPlaybookLaunch: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.playbookLaunch, payload),
  onboardingPlaybookGapAnswers: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.playbookGapAnswers, payload),
  onboardingPlaybookMcqAnswer: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.playbookMcqAnswer, payload),
  onboardingPrecisionStart: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.precisionStart, payload),
  onboardingPrecisionAnswer: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.precisionAnswer, payload),
  onboardingGapQuestionsStart: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.gapQuestionsStart, payload),
  onboardingReset: (payload: Record<string, unknown>) =>
    apiPost<Record<string, unknown>>(API_ROUTES.onboarding.reset, payload),
  request: apiRequest,
};

export const STAGE_LABELS: Record<string, string> = {
  thinking: 'Thinking',
  scraping: 'Fetching data',
  scripting: 'Processing',
  generating: 'Generating output',
  merging: 'Merging',
  done: 'Done',
  error: 'Error',
};

function getApiBase(): string {
  return getApiBaseRequired();
}

function withAuthActor<T extends Record<string, unknown>>(payload: T): T {
  const userId = getUserIdFromJwt();
  if (!userId) return payload;
  return {
    ...payload,
    userId,
  } as T;
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  return apiRequest(`${getApiBase()}${path}`, { ...options, credentials: 'include' });
}

type ApiErrorShape = { error?: string; detail?: string; message?: string };

async function extractApiError(response: Response): Promise<string> {
  const fallback = `Request failed (${response.status})`;
  try {
    const payload = (await response.json()) as ApiErrorShape;
    return payload.detail || payload.error || payload.message || fallback;
  } catch {
    return fallback;
  }
}

async function parseJsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(await extractApiError(response));
  }
  return (await response.json()) as T;
}

async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, init);
  return parseJsonOrThrow<T>(response);
}

async function apiJsonPost<T>(path: string, payload: unknown): Promise<T> {
  return apiJson<T>(path, { method: 'POST', body: JSON.stringify(payload) });
}

export async function getSkillCalls(messageId: string): Promise<{ skillCalls: SkillCallFull[] }> {
  return apiJson<{ skillCalls: SkillCallFull[] }>(
    `${API_ROUTES.aiChat.skillCalls}?messageId=${encodeURIComponent(messageId)}`,
  );
}

export async function getTokenUsage(messageId: string): Promise<TokenUsage> {
  return apiJson<TokenUsage>(`${API_ROUTES.aiChat.tokenUsage}?messageId=${encodeURIComponent(messageId)}`);
}


async function readSseStream(response: Response, callbacks: StreamCallbacks): Promise<StreamResult> {
  if (!response.body) throw new Error('No response body');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result: StreamResult = { conversationId: '' };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6)) as {
          token?: string;
          stage?: PipelineStage;
          label?: string;
          stageIndex?: number;
          done?: boolean;
          conversationId?: string;
          messageId?: string;
          runId?: string;
          model?: string;
          durationMs?: number;
          stageOutputs?: Record<string, string>;
          outputFile?: string;
          planId?: string;
          planMessageId?: string;
          planMarkdown?: string;
          error?: string;
          errorAtStage?: PipelineStage;
          agentId?: string;
          progress?: ProgressEvent;
          backgroundExecution?: boolean;
          assistantMessageId?: string;
          mode?: string;
          journeyStep?: string;
          taskStream?: { streamId: string; taskType: string };
        };

        if (data.error && !data.stage) throw new Error(data.error);
        if (data.token) callbacks.onToken?.(data.token);
        if (data.stage && data.stage !== 'error') {
          callbacks.onStage?.(data.stage, data.label ?? data.stage, data.stageIndex ?? 0, data.agentId as AgentId | undefined);
        }
        if (data.progress) callbacks.onProgress?.(data.progress as ProgressEvent);

        if (data.stage === 'error') {
          const err = new Error(data.error ?? 'Pipeline error') as Error & { errorAtStage?: PipelineStage };
          err.errorAtStage = data.errorAtStage;
          throw err;
        }

        if (data.done) {
          result = {
            conversationId: data.conversationId ?? '',
            messageId: data.messageId,
            agentId: data.agentId as AgentId | undefined,
            runId: data.runId,
            model: data.model,
            durationMs: data.durationMs,
            stageOutputs: data.stageOutputs,
            outputFile: data.outputFile,
            planId: data.planId,
            planMessageId: data.planMessageId,
            planMarkdown: data.planMarkdown,
            backgroundExecution: data.backgroundExecution,
            assistantMessageId: data.assistantMessageId,
            mode: data.mode as string | undefined,
            journeyStep: data.journeyStep as string | undefined,
            taskStream: data.taskStream,
          };
        }
      } catch (e) {
        if (e instanceof Error && e.message !== 'Unexpected end of JSON input') throw e;
      }
    }
  }
  return result;
}

export async function sendMessageStream(opts: SendMessageStreamOptions): Promise<StreamResult> {
  const { message, conversationId, agentId, retryFromStage, stageOutputs, callbacks } = opts;
  const response = await apiRequest(`${getApiBase()}${API_ROUTES.aiChat.stream}`, {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify(
      withAuthActor({
        message,
        conversationId,
        agentId,
        retryFromStage,
        stageOutputs,
      }),
    ),
  });
  if (!response.ok) {
    throw new Error(await extractApiError(response));
  }
  return readSseStream(response, callbacks);
}

export async function getPlanStatus(planId: string): Promise<{ planId: string; status: string; runningTaskRefFound?: boolean; errorMessage?: string }> {
  return apiJson<{ planId: string; status: string; runningTaskRefFound?: boolean; errorMessage?: string }>(
    `${API_ROUTES.aiChat.planStatus}?planId=${encodeURIComponent(planId)}`,
  );
}

export async function sendMessage(opts: {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
}): Promise<{
  message?: string;
  conversationId: string;
  mode?: string;
  status?: string;
  optionSelected?: string;
  requiresStream?: boolean;
  backgroundExecution?: boolean;
  planId?: string;
  planMessageId?: string;
  planMarkdown?: string;
  assistantMessageId?: string;
  agentId?: AgentId;
  /** Task stream metadata when background task is started */
  taskStream?: {
    streamId: string;
    taskType: string;
  };
}> {
  return apiJsonPost<{
    message?: string;
    conversationId: string;
    mode?: string;
    status?: string;
    optionSelected?: string;
    requiresStream?: boolean;
    backgroundExecution?: boolean;
    planId?: string;
    planMessageId?: string;
    planMarkdown?: string;
    assistantMessageId?: string;
    agentId?: AgentId;
    taskStream?: {
      streamId: string;
      taskType: string;
    };
  }>(
    API_ROUTES.aiChat.message,
    withAuthActor({
      message: opts.message,
      conversationId: opts.conversationId,
      agentId: opts.agentId,
    }),
  );
}


export async function getInitialMessage(agentId: AgentId): Promise<ChatMessage | null> {
  const result = await apiJson<{ agentId: AgentId; message: ChatMessage | null }>(
    `${API_ROUTES.aiChat.initialMessage}?agentId=${encodeURIComponent(agentId)}`,
  );
  return result.message;
}

export async function getMessages(conversationId?: string): Promise<{
  messages: ChatMessage[];
  conversationId: string;
  agentId?: AgentId;
  lastStageOutputs?: Record<string, string>;
  lastOutputFile?: string;
}> {
  const params = new URLSearchParams();
  if (conversationId) params.set('conversationId', conversationId);
  const userId = getUserIdFromJwt();
  if (userId) params.set('userId', userId);
  const q = params.toString() ? `?${params}` : '';
  return apiJson<{
    messages: ChatMessage[];
    conversationId: string;
    agentId?: AgentId;
    lastStageOutputs?: Record<string, string>;
    lastOutputFile?: string;
  }>(`${API_ROUTES.aiChat.messages}${q}`);
}

export async function getConversations(): Promise<{ conversations: ConversationSummary[] }> {
  const userId = getUserIdFromJwt();
  if (!userId) {
    return { conversations: [] };
  }
  const params = new URLSearchParams();
  params.set('userId', userId);
  const q = `?${params}`;
  return apiJson<{ conversations: ConversationSummary[] }>(`${API_ROUTES.aiChat.conversations}${q}`);
}

export async function getPlaybookHistory(
  opts?: { limit?: number; offset?: number },
): Promise<{ playbooks: PlaybookHistoryItem[]; pagination?: { limit: number; offset: number; total: number; hasMore: boolean } }> {
  const params = new URLSearchParams();
  const userId = getUserIdFromJwt();
  if (userId) params.set('userId', userId);
  if (opts?.limit != null) params.set('limit', String(opts.limit));
  if (opts?.offset != null) params.set('offset', String(opts.offset));
  const q = params.toString() ? `?${params}` : '';
  return apiJson<{ playbooks: PlaybookHistoryItem[]; pagination?: { limit: number; offset: number; total: number; hasMore: boolean } }>(
    `${API_ROUTES.aiChat.playbookHistory}${q}`,
  );
}

export async function getPlaybookStatus(onboardingId: string): Promise<{
  onboarding_id: string;
  playbook_status: string;
  website_url: string;
  content: { playbook: string; website_audit: string; context_brief: string; icp_card: string } | null;
}> {
  return apiJson(API_ROUTES.onboarding.playbookStatus(onboardingId));
}

export interface WebsiteAuditStreamCallbacks {
  onToken?: (token: string) => void;
  onDone?: (fullText: string) => void;
  onError?: (message: string) => void;
}

export async function streamWebsiteAudit(
  onboardingId: string,
  callbacks: WebsiteAuditStreamCallbacks,
): Promise<void> {
  const response = await apiRequest(`${getApiBase()}${API_ROUTES.onboarding.websiteAuditStream}`, {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify({ onboarding_id: onboardingId }),
  });
  if (!response.ok) throw new Error(await extractApiError(response));
  if (!response.body) throw new Error('No response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6)) as { type: string; token?: string; full_text?: string; message?: string };
        if (data.type === 'token' && data.token) {
          callbacks.onToken?.(data.token);
        } else if (data.type === 'done') {
          callbacks.onDone?.(data.full_text ?? '');
          return;
        } else if (data.type === 'error') {
          callbacks.onError?.(data.message ?? 'Audit stream error');
          return;
        }
      } catch {
        // ignore malformed lines
      }
    }
  }
}

export async function getPlaybookRun(runId: string): Promise<PlaybookRunDetail> {
  return apiJson<PlaybookRunDetail>(API_ROUTES.aiChat.playbookRun(runId));
}

export async function fetchSkills(): Promise<SkillMeta[]> {
  return apiJson<SkillMeta[]>(API_ROUTES.aiChat.skills);
}

export async function getAgents(): Promise<{ agents: UiAgent[] }> {
  return apiJson<{ agents: UiAgent[] }>(API_ROUTES.agents.base);
}

export async function getAgent(id: AgentId): Promise<{ agent: UiAgent }> {
  return apiJson<{ agent: UiAgent }>(API_ROUTES.agents.byId(id));
}

export async function createAgent(agent: UiAgent): Promise<{ agent: UiAgent }> {
  return apiJsonPost<{ agent: UiAgent }>(API_ROUTES.agents.base, agent);
}

export async function updateAgent(id: AgentId, data: Partial<Omit<UiAgent, 'id'>>): Promise<{ agent: UiAgent }> {
  return apiJson<{ agent: UiAgent }>(API_ROUTES.agents.byId(id), {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteAgent(id: AgentId): Promise<void> {
  const response = await apiFetch(API_ROUTES.agents.byId(id), { method: 'DELETE' });
  if (!response.ok) throw new Error(await extractApiError(response));
}

export async function getProducts(opts?: { activeOnly?: boolean }): Promise<{ products: Product[] }> {
  const params = new URLSearchParams();
  if (opts?.activeOnly != null) params.set('active_only', String(opts.activeOnly));
  const q = params.toString() ? `?${params}` : '';
  return apiJson<{ products: Product[] }>(`${API_ROUTES.products.base}${q}`);
}

export async function createProduct(product: Product): Promise<{ product: Product }> {
  return apiJsonPost<{ product: Product }>(API_ROUTES.products.base, product);
}

export async function updateProduct(id: string, data: Partial<Omit<Product, 'id'>>): Promise<{ product: Product }> {
  return apiJson<{ product: Product }>(API_ROUTES.products.byId(id), {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteProduct(id: string): Promise<void> {
  const response = await apiFetch(API_ROUTES.products.byId(id), { method: 'DELETE' });
  if (!response.ok) throw new Error(await extractApiError(response));
}

export async function createConversation(opts: {
  agentId: AgentId;
}): Promise<{ conversationId: string; agentId: AgentId; messages: ChatMessage[] }> {
  return apiJsonPost<{ conversationId: string; agentId: AgentId; messages: ChatMessage[] }>(
    API_ROUTES.aiChat.newConversation,
    withAuthActor({ agentId: opts.agentId }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await apiFetch(API_ROUTES.aiChat.conversationById(id), { method: 'DELETE' });
  if (!response.ok) throw new Error(await extractApiError(response));
}

/** Check if user has access to a given agent (paid plan check). */
export interface AgentAccessResult {
  allowed: boolean;
  reason?: string;
  required_plan_slug?: string;
  required_plan_name?: string;
  required_plan_price?: number;
}

export async function checkAgentAccess(agentId: string): Promise<AgentAccessResult> {
  return apiJson<AgentAccessResult>(
    `${API_ROUTES.aiChat.agentAccess}?agentId=${encodeURIComponent(agentId)}`,
  );
}

export interface TaskStreamCallbacks {
  onToken?: (token: string) => void;
  onStage?: (stage: string, label: string) => void;
  onProgress?: (data: Record<string, unknown>) => void;
  onDone?: (data: Record<string, unknown>) => void;
  onError?: (message: string) => void;
}

export async function subscribeToTaskStream(
  streamId: string,
  callbacks: TaskStreamCallbacks,
): Promise<void> {
  const url = `${getApiBase()}${API_ROUTES.taskStream.eventsByStreamId(streamId)}`;
  const response = await apiRequest(url, { credentials: 'include' });
  if (!response.ok) throw new Error(await extractApiError(response));
  if (!response.body) throw new Error('No response body');

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6)) as Record<string, unknown>;
        const type = data.type as string | undefined;
        if (type === 'token' && typeof data.token === 'string') {
          callbacks.onToken?.(data.token);
        } else if (type === 'stage') {
          callbacks.onStage?.(String(data.stage ?? ''), String(data.label ?? ''));
        } else if (type === 'progress') {
          callbacks.onProgress?.(data);
        } else if (type === 'done') {
          callbacks.onDone?.(data);
          return;
        } else if (type === 'error') {
          callbacks.onError?.(String(data.message ?? 'Stream error'));
          return;
        }
      } catch {
        // ignore malformed lines
      }
    }
  }
}
