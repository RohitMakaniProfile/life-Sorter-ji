// ==============================
// BASIC TYPES
// ==============================

export type Role = 'user' | 'assistant';

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

// ==============================
// PROGRESS EVENTS
// ==============================

export interface ProgressMeta {
  kind?: string; // e.g. 'skill-call'
  [key: string]: any;
}

export interface ProgressEvent {
  stage: PipelineStage;
  message: string;
  timestamp?: number;
  meta?: ProgressMeta;
}

// ==============================
// PIPELINE STATE
// ==============================

export interface PipelineState {
  currentStage: PipelineStage;
  agentId: AgentId;
  stageOutputs: Record<string, string>;
  progressEvents: ProgressEvent[];
  outputFile?: string;
  error?: string;
}

// ==============================
// MESSAGE TYPES
// ==============================

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

export interface RichMessage {
  role: Role;
  content: string;
  formId?: string;
  options?: string[];
  createdAt?: string;

  // optional UI metadata
  agentId?: AgentId;
  outputFile?: string;
  tokenUsage?: TokenUsage;
  messageId?: string;
  skillsCount?: number;
  kind?: 'plan' | 'final';
  planId?: string;
}

// ==============================
// STREAMING API TYPES
// ==============================

export interface StreamCallbacks {
  onStage?: (stage: PipelineStage) => void;
  onProgress?: (event: ProgressEvent) => void;
  onToken?: (token: string) => void;
}

export interface SendMessageStreamInput {
  message: string;
  conversationId?: string;
  agentId: AgentId;

  retryFromStage?: PipelineStage;
  stageOutputs?: Record<string, string>;

  callbacks: StreamCallbacks;
}

export interface SendMessageStreamResult {
  conversationId?: string;
  model?: string;

  stageOutputs?: Record<string, string>;
  outputFile?: string;
  tokenUsage?: TokenUsage;
}

// ==============================
// BACKEND MESSAGE FORMAT
// ==============================

export interface BackendMessage {
  role: Role;
  content: string;
  formId?: string;
  options?: string[];
}

export interface GetMessagesResponse {
  conversationId?: string;
  agentId?: AgentId;
  messages?: BackendMessage[];
  lastStageOutputs?: Record<string, string>;
}