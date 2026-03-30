import { API_ROUTES } from '../routes';
import { apiGet, apiPost, apiRequest } from '../http';
import { getApiBaseRequired } from '../../config/apiBase';
import type {
  AgentId,
  ChatMessage,
  ConversationSummary,
  CreatePlanResponse,
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
  verifyOtp: (payload: { session_id: string; otp_session_id: string; otp_code: string; google_email?: string; google_name?: string }) =>
    apiPost<{ success: boolean; verified: boolean; token?: string; user?: Record<string, unknown>; message?: string }>(
      API_ROUTES.auth.verifyOtp,
      payload,
    ),

  createAgentSession: () => apiPost<{ session_id: string }>(API_ROUTES.agent.session, {}),
  getAgentSession: (sessionId: string) => apiGet<any>(API_ROUTES.agent.sessionById(sessionId)),
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
  getAgentSessionStatus: (sessionId: string) => apiGet<any>(API_ROUTES.agent.sessionStatus(sessionId)),
  getWebsiteSnapshot: (sessionId: string) => apiGet<any>(API_ROUTES.agent.websiteSnapshot(sessionId)),
  getContextPool: (sessionId: string) => apiGet<any>(API_ROUTES.agent.contextPool(sessionId)),

  playbookStart: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.start, payload),
  playbookGenerate: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.generate, payload),
  playbookGapAnswers: (payload: Record<string, unknown>) => apiPost<any>(API_ROUTES.playbook.gapAnswers, payload),
  playbookGenerateStream: (
    payload: Record<string, unknown>,
    callbacks: {
      onToken?: (token: string) => void;
      onStage?: (stage: string, label: string) => void;
      onDone?: (result: { playbook: string; website_audit: string; context_brief: string; icp_card: string }) => void;
      onError?: (message: string) => void;
    },
  ) => playbookGenerateStream(payload, callbacks),

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

export async function createPlan(opts: {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
  cancelPlanId?: string;
}): Promise<CreatePlanResponse> {
  return apiJsonPost<CreatePlanResponse>(API_ROUTES.aiChat.plan, opts);
}

export async function createPlanStream(opts: {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
  cancelPlanId?: string;
  callbacks: StreamCallbacks;
}): Promise<StreamResult> {
  const response = await apiRequest(`${getApiBase()}${API_ROUTES.aiChat.planStream}`, {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify({
      message: opts.message,
      conversationId: opts.conversationId,
      agentId: opts.agentId,
      cancelPlanId: opts.cancelPlanId,
    }),
  });
  if (!response.ok) {
    throw new Error(await extractApiError(response));
  }
  return readSseStream(response, opts.callbacks);
}

export async function approvePlanStream(opts: {
  planId: string;
  conversationId?: string;
  planMarkdown?: string;
  agentId?: AgentId;
  callbacks: StreamCallbacks;
}): Promise<StreamResult> {
  const response = await apiRequest(`${getApiBase()}${API_ROUTES.aiChat.planApproveStream}`, {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify(opts),
  });
  if (!response.ok) {
    throw new Error(await extractApiError(response));
  }
  return readSseStream(response, opts.callbacks);
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
    body: JSON.stringify({ message, conversationId, agentId, retryFromStage, stageOutputs }),
  });
  if (!response.ok) {
    throw new Error(await extractApiError(response));
  }
  return readSseStream(response, callbacks);
}

export async function sendMessage(message: string, conversationId?: string): Promise<{ message: string; conversationId: string }> {
  return apiJsonPost<{ message: string; conversationId: string }>(API_ROUTES.aiChat.message, { message, conversationId });
}

export async function getMessages(conversationId?: string): Promise<{
  messages: ChatMessage[];
  conversationId: string;
  agentId?: AgentId;
  lastStageOutputs?: Record<string, string>;
  lastOutputFile?: string;
}> {
  const q = conversationId ? `?conversationId=${encodeURIComponent(conversationId)}` : '';
  return apiJson<{
    messages: ChatMessage[];
    conversationId: string;
    agentId?: AgentId;
    lastStageOutputs?: Record<string, string>;
    lastOutputFile?: string;
  }>(`${API_ROUTES.aiChat.messages}${q}`);
}

export async function getConversations(): Promise<{ conversations: ConversationSummary[] }> {
  return apiJson<{ conversations: ConversationSummary[] }>(API_ROUTES.aiChat.conversations);
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

export async function playbookGenerateStream(
  payload: Record<string, unknown>,
  callbacks: {
    onToken?: (token: string) => void;
    onStage?: (stage: string, label: string) => void;
    onDone?: (result: { playbook: string; website_audit: string; context_brief: string; icp_card: string }) => void;
    onError?: (message: string) => void;
  },
): Promise<void> {
  const response = await apiRequest(`${getApiBase()}${API_ROUTES.playbook.generateStream}`, {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify(payload),
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
        const data = JSON.parse(line.slice(6)) as {
          type: string;
          token?: string;
          stage?: string;
          label?: string;
          playbook?: string;
          website_audit?: string;
          context_brief?: string;
          icp_card?: string;
          message?: string;
        };
        if (data.type === 'token' && data.token) callbacks.onToken?.(data.token);
        if (data.type === 'stage') callbacks.onStage?.(data.stage ?? '', data.label ?? data.stage ?? '');
        if (data.type === 'done') callbacks.onDone?.({ playbook: data.playbook ?? '', website_audit: data.website_audit ?? '', context_brief: data.context_brief ?? '', icp_card: data.icp_card ?? '' });
        if (data.type === 'error') callbacks.onError?.(data.message ?? 'Unknown error');
      } catch {
        // skip malformed lines
      }
    }
  }
}

