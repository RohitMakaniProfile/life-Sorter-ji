export type AgentId = string;

export type PipelineStage =
  | 'thinking'
  | 'done'
  | 'error'
  | 'scraping'
  | 'scripting'
  | 'generating'
  | 'merging'
  | 'researching';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  formId?: string;
  options?: string[];
  createdAt?: string;
  outputFile?: string;
  messageId?: string;
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
  errorAtStage?: PipelineStage;
}

export interface SendMessageStreamOptions {
  message: string;
  conversationId?: string;
  agentId?: AgentId;
  retryFromStage?: PipelineStage;
  stageOutputs?: Record<string, string>;
  callbacks: StreamCallbacks;
}

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

