import { getApiBaseRequired } from '../../config/apiBase';

export type AgentId = string;

export type PipelineStage =
  | 'thinking'
  | 'done'
  | 'error'
  // amazon-video
  | 'scraping'
  | 'scripting'
  | 'generating'
  | 'merging'
  // business-research
  | 'researching';

// Legacy UI components still expect some default pipeline stages/labels.
// For now, keep a minimal shared definition so PipelineTracker renders.
export const PIPELINE_STAGES: PipelineStage[] = [
  'thinking',
  'scraping',
  'scripting',
  'generating',
  'merging',
  'done',
];

export const STAGE_LABELS: Record<string, string> = {
  thinking:   'Thinking',
  scraping:   'Fetching data',
  scripting:  'Processing',
  generating: 'Generating output',
  merging:    'Merging',
  done:       'Done',
  error:      'Error',
};

function getApiBase(): string {
  return getApiBaseRequired();
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(`${getApiBase()}${path}`, { ...options, credentials: 'include' });
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  createdAt?: string;
  /** Persisted output file path — present on assistant messages that produced a video */
  outputFile?: string;
  messageId?: string;
  /** Number of skill calls for this (assistant) message; details loaded on expand */
  skillsCount?: number;
  kind?: 'plan' | 'final';
  planId?: string;
}

export interface CreatePlanResponse {
  conversationId: string;
  planId: string;
  planMessageId: string;
  planMarkdown: string;
  agentId?: AgentId;
}

export async function createPlan(opts: { message: string; conversationId?: string; agentId?: AgentId; cancelPlanId?: string }): Promise<CreatePlanResponse> {
  const res = await apiFetch('/api/chat/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Plan request failed' })) as { error?: string };
    throw new Error(err.error ?? 'Plan request failed');
  }
  return res.json() as Promise<CreatePlanResponse>;
}

export async function createPlanStream(opts: {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
  cancelPlanId?: string;
  callbacks: StreamCallbacks;
}): Promise<StreamResult> {
  const res = await fetch(`${getApiBase()}/api/chat/plan/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      message: opts.message,
      conversationId: opts.conversationId,
      agentId: opts.agentId,
      cancelPlanId: opts.cancelPlanId,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Plan request failed' })) as { error?: string };
    throw new Error(err.error ?? 'Plan request failed');
  }
  return readSseStream(res, opts.callbacks);
}

export async function approvePlanStream(opts: {
  planId: string;
  conversationId?: string;
  planMarkdown?: string;
  agentId?: AgentId;
  callbacks: StreamCallbacks;
}): Promise<StreamResult> {
  const res = await fetch(`${getApiBase()}/api/chat/plan/approve/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(opts),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Approve request failed' })) as { error?: string };
    throw new Error(err.error ?? 'Approve request failed');
  }
  return readSseStream(res, opts.callbacks);
}

/** Skill call from GET /api/chat/skill-calls (full document with output array). */
export interface SkillCallFull {
  id: string;
  skillId: string;
  runId: string;
  state: 'running' | 'done' | 'error';
  input: Record<string, unknown>;
  output: Array<{
    type: string;
    event?: string;
    payload?: Record<string, unknown>;
    text?: string;
    data?: unknown;
    at?: string;
  }>;
  error?: string;
  startedAt: string;
  endedAt?: string;
  durationMs?: number;
}

export async function getSkillCalls(messageId: string): Promise<{ skillCalls: SkillCallFull[] }> {
  const res = await apiFetch(`/api/chat/skill-calls?messageId=${encodeURIComponent(messageId)}`);
  if (!res.ok) throw new Error('Failed to load skill calls');
  return res.json() as Promise<{ skillCalls: SkillCallFull[] }>;
}

// ─── Token usage API ──────────────────────────────────────────────────────────

export interface TokenUsageEntry {
  stage: string;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
}

export interface TokenUsage {
  entries: TokenUsageEntry[];
  totalInputTokens: number;
  totalOutputTokens: number;
}

export async function getTokenUsage(messageId: string): Promise<TokenUsage> {
  const res = await apiFetch(`/api/chat/token-usage?messageId=${encodeURIComponent(messageId)}`);
  if (!res.ok) throw new Error('Failed to load token usage');
  return res.json() as Promise<TokenUsage>;
}

export interface ConversationSummary {
  id: string;
  agentId: AgentId;
  title: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ProgressEvent {
  stage: PipelineStage;
  type: 'url' | 'page' | 'search' | 'data' | 'task' | 'info' | 'done';
  message: string;
  value?: number;
  unit?: string;
  // Optional structured metadata from backend (e.g. skill-call timeline)
  meta?: Record<string, unknown>;
}

export interface StreamCallbacks {
  onToken?: (token: string) => void;
  onStage?: (stage: PipelineStage, label: string, stageIndex: number, agentId?: AgentId) => void;
  onProgress?: (event: ProgressEvent) => void;
}

export interface StreamResult {
  conversationId: string;
  messageId?: string;
  agentId?: AgentId;
  runId?: string;
  model?: string;
  durationMs?: number;
  stageOutputs?: Record<string, string>;
  outputFile?: string;
  planId?: string;
  planMessageId?: string;
  planMarkdown?: string;
  /** Set when the pipeline errored — the stage where it failed */
  errorAtStage?: PipelineStage;
}

async function readSseStream(
  response: Response,
  callbacks: StreamCallbacks
): Promise<StreamResult> {
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

        if (data.token) {
          callbacks.onToken?.(data.token);
        }

        if (data.stage && data.stage !== 'error') {
          callbacks.onStage?.(data.stage, data.label ?? data.stage, data.stageIndex ?? 0, data.agentId as AgentId | undefined);
        }

        if (data.progress) {
          callbacks.onProgress?.(data.progress as ProgressEvent);
        }

        if (data.stage === 'error') {
          // Attach errorAtStage to the error so ChatPage can freeze the
          // pipeline tracker at the correct step
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

export interface SendMessageStreamOptions {
  message: string;
  conversationId?: string;
  /** UI agent id; backend resolves allowed skills from DB */
  agentId?: AgentId;
  retryFromStage?: PipelineStage;
  stageOutputs?: Record<string, string>;
  callbacks: StreamCallbacks;
}

export async function sendMessageStream(opts: SendMessageStreamOptions): Promise<StreamResult> {
  const { message, conversationId, agentId, retryFromStage, stageOutputs, callbacks } = opts;

  const res = await fetch(`${getApiBase()}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ message, conversationId, agentId, retryFromStage, stageOutputs }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Stream request failed' })) as { error?: string };
    throw new Error(err.error ?? 'Stream request failed');
  }

  return readSseStream(res, callbacks);
}

export async function sendMessage(
  message: string,
  conversationId?: string
): Promise<{ message: string; conversationId: string }> {
  const res = await apiFetch('/api/chat/message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversationId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: 'Send failed' })) as { error?: string };
    throw new Error(err.error ?? 'Send failed');
  }
  return res.json() as Promise<{ message: string; conversationId: string }>;
}

export async function getMessages(conversationId?: string): Promise<{
  messages: ChatMessage[];
  conversationId: string;
  agentId?: AgentId;
  lastStageOutputs?: Record<string, string>;
  lastOutputFile?: string;
}> {
  const q = conversationId ? `?conversationId=${encodeURIComponent(conversationId)}` : '';
  const res = await apiFetch(`/api/chat/messages${q}`);
  if (!res.ok) throw new Error('Failed to load messages');
  return res.json() as Promise<{
    messages: ChatMessage[];
    conversationId: string;
    agentId?: AgentId;
    lastStageOutputs?: Record<string, string>;
    lastOutputFile?: string;
  }>;
}

export async function getConversations(): Promise<{ conversations: ConversationSummary[] }> {
  const res = await apiFetch('/api/chat/conversations');
  if (!res.ok) throw new Error('Failed to load conversations');
  return res.json() as Promise<{ conversations: ConversationSummary[] }>;
}

// ─── Skills API ────────────────────────────────────────────────────────────────

export interface SkillMeta {
  id: string;
  name: string;
  emoji: string;
  description: string;
  stages: string[];
  stageLabels: Record<string, string>;
}

export interface UiAgent {
  id: AgentId;
  name: string;
  emoji: string;
  description: string;
  allowedSkillIds: string[];
  skillSelectorContext?: string;
  finalOutputFormattingContext?: string;
}

export async function fetchSkills(): Promise<SkillMeta[]> {
  const res = await apiFetch('/api/chat/skills');
  if (!res.ok) throw new Error('Failed to load skills');
  return res.json() as Promise<SkillMeta[]>;
}

// ─── Agents API (global list, backend-stored) ──────────────────────────────────

export async function getAgents(): Promise<{ agents: UiAgent[] }> {
  const res = await apiFetch('/api/agents');
  if (!res.ok) throw new Error('Failed to load agents');
  return res.json() as Promise<{ agents: UiAgent[] }>;
}

export async function getAgent(id: AgentId): Promise<{ agent: UiAgent }> {
  const res = await apiFetch(`/api/agents/${encodeURIComponent(id)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? 'Failed to load agent');
  }
  return res.json() as Promise<{ agent: UiAgent }>;
}

export async function createAgent(agent: UiAgent): Promise<{ agent: UiAgent }> {
  const res = await apiFetch('/api/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(agent),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? 'Failed to create agent');
  }
  return res.json() as Promise<{ agent: UiAgent }>;
}

export async function updateAgent(id: AgentId, data: Partial<Omit<UiAgent, 'id'>>): Promise<{ agent: UiAgent }> {
  const res = await apiFetch(`/api/agents/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? 'Failed to update agent');
  }
  return res.json() as Promise<{ agent: UiAgent }>;
}

export async function deleteAgent(id: AgentId): Promise<void> {
  const res = await apiFetch(`/api/agents/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(err.error ?? 'Failed to delete agent');
  }
}

export async function deleteConversation(id: string): Promise<void> {
  await apiFetch(`/api/chat/conversations/${id}`, { method: 'DELETE' });
}
