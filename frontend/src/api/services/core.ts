import { API_ROUTES } from '../routes';
import { apiGet, apiPost, apiRequest } from '../http';
import { getPhase2ActorFields } from '../phase2Session';
import { getApiBaseRequired } from '../../config/apiBase';
import type {
  AgentId,
  ChatMessage,
  ConversationSummary,
  PipelineStage,
  ProgressEvent,
  SendMessageStreamOptions,
  SkillCallFull,
  SkillMeta,
  StreamCallbacks,
  StreamResult,
  TokenUsage,
  UiAgent,
} from '../types';

export const coreApi = {
  authMe: () => apiGet<{ authenticated: boolean; user: Record<string, unknown> }>(API_ROUTES.auth.me),
  googleAuth: (payload: { session_id: string; google_id: string; email: string; name: string; avatar_url?: string }) =>
    apiPost<{ success: boolean; token?: string; user?: Record<string, unknown> }>(API_ROUTES.auth.google, payload),
  sendOtp: (payload: { session_id: string; phone_number: string }) =>
    apiPost<{ success: boolean; otp_session_id?: string; message?: string }>(API_ROUTES.auth.sendOtp, payload),
  verifyOtp: (payload: { session_id: string; otp_session_id: string; otp_code: string }) =>
    apiPost<{ success: boolean; verified: boolean; token?: string; user?: Record<string, unknown>; message?: string }>(
      API_ROUTES.auth.verifyOtp,
      payload,
    ),

  createAgentSession: () => apiPost<{ session_id: string }>(API_ROUTES.agent.session, {}),
  getAgentSession: (sessionId: string) => apiGet<any>(API_ROUTES.agent.sessionById(sessionId, 'summary')),
  getAgentSessionView: (sessionId: string, view: 'summary' | 'status' | 'context_pool' | 'website_snapshot') =>
    apiGet<any>(API_ROUTES.agent.sessionById(sessionId, view)),
  patchAgentSession: (sessionId: string, payload: Record<string, unknown>) =>
    apiFetch(API_ROUTES.agent.patchSession(sessionId), {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }).then(async (res) => {
      if (!res.ok) throw new Error(await extractApiError(res));
      return (await res.json()) as any;
    }),
  advanceAgentSession: (
    sessionId: string,
    payload: { action?: string; task?: string; question_index?: number; answer?: string },
  ) =>
    apiPost<any>(API_ROUTES.agent.advanceSession(sessionId), payload),

  playbookStart: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.start, payload),
  playbookGenerate: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.generate, payload),
  playbookGapAnswers: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.gapAnswers, payload),

  createPaymentOrder: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.payments.createOrder, payload),
  getPaymentStatus: (orderId: string) => apiGet<any>(API_ROUTES.payments.status(orderId)),

  saveIdea: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.legacy.saveIdea, payload),
  searchCompanies: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.legacy.searchCompanies, payload),
  chat: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.legacy.chat, payload),

  marketIntelligence: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.legacy.marketIntelligence, payload),

  // Raw passthrough for non-JSON/non-standard calls.
  request: apiRequest,
};

export const PIPELINE_STAGES: PipelineStage[] = [
  'thinking',
  'scraping',
  'scripting',
  'generating',
  'merging',
  'done',
];

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

function withPhase2Actor<T extends Record<string, unknown>>(payload: T): T {
  const actor = getPhase2ActorFields();
  if (!actor.userId && !actor.sessionId) return payload;
  return { ...payload, ...actor };
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
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
      withPhase2Actor({
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

export async function getPlanStatus(planId: string): Promise<{ planId: string; status: string; runningTaskRefFound?: boolean }> {
  return apiJson<{ planId: string; status: string; runningTaskRefFound?: boolean }>(
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
  }>(
    API_ROUTES.aiChat.message,
    withPhase2Actor({
      message: opts.message,
      conversationId: opts.conversationId,
      agentId: opts.agentId,
    }),
  );
}

export async function sendMessageBackground(opts: {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
  planId?: string;
}): Promise<{
  conversationId: string;
  status?: string;
  optionSelected?: string;
  backgroundExecution?: boolean;
  planId?: string;
  assistantMessageId?: string;
  agentId?: AgentId;
}> {
  return apiJsonPost<{
    conversationId: string;
    status?: string;
    optionSelected?: string;
    backgroundExecution?: boolean;
    planId?: string;
    assistantMessageId?: string;
    agentId?: AgentId;
  }>(
    API_ROUTES.aiChat.messageBackground,
    withPhase2Actor({
      message: opts.message,
      conversationId: opts.conversationId,
      agentId: opts.agentId,
      planId: opts.planId,
    }),
  );
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
  const actor = getPhase2ActorFields();
  if (actor.userId) params.set('userId', actor.userId);
  if (actor.sessionId) params.set('sessionId', actor.sessionId);
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
  const params = new URLSearchParams();
  const actor = getPhase2ActorFields();
  if (actor.userId) params.set('userId', actor.userId);
  if (actor.sessionId) params.set('sessionId', actor.sessionId);
  const q = params.toString() ? `?${params}` : '';
  return apiJson<{ conversations: ConversationSummary[] }>(`${API_ROUTES.aiChat.conversations}${q}`);
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

export async function deleteConversation(id: string): Promise<void> {
  const response = await apiFetch(API_ROUTES.aiChat.conversationById(id), { method: 'DELETE' });
  if (!response.ok) throw new Error(await extractApiError(response));
}

