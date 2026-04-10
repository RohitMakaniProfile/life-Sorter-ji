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
  allowCustomAnswer?: boolean;
  createdAt?: string;
  outputFile?: string;
  messageId?: string;
  skillsCount?: number;
  kind?: 'plan' | 'final';
  planId?: string;
  journeyStep?: string;
  journeySelections?: Record<string, string>;
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

export interface PlaybookHistoryItem {
  runId: string;
  sessionId: string;
  conversationId?: string;
  title: string;
  outcome?: string;
  domain?: string;
  task?: string;
  createdAt: string;
  updatedAt: string;
}

export interface PlaybookRunDetail {
  runId: string;
  sessionId: string;
  title: string;
  outcome?: string;
  domain?: string;
  task?: string;
  playbookData: {
    playbook?: string;
    websiteAudit?: string;
    contextBrief?: string;
    icpCard?: string;
  };
  crossAgentActions?: Array<{
    label: string;
    icon?: string;
    agentId: string;
    initialMessage: string;
  }>;
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
  backgroundExecution?: boolean;
  assistantMessageId?: string;
  mode?: string;
  journeyStep?: string;
  /** Task stream metadata when background task is started */
  taskStream?: {
    streamId: string;
    taskType: string;
  };
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
  isLocked?: boolean;
  visibility?: 'public' | 'private';
  createdByUserId?: string | null;
  allowedSkillIds: string[];
  skillSelectorContext?: string;
  finalOutputFormattingContext?: string;
}

export type ConfigValueType = 'string' | 'number' | 'boolean' | 'json' | 'markdown';

export interface SystemConfigEntry {
  key: string;
  value: string;
  type: ConfigValueType;
  description: string;
  updatedAt: string;
}

export interface ServiceHealthEntry {
  name: string;
  ok: boolean;
  detail: string;
}

export interface RecentErrorEntry {
  source: string;
  at: string;
  message: string;
  meta?: Record<string, unknown>;
}

export interface ObservabilitySnapshot {
  snapshotAt: string;
  services: ServiceHealthEntry[];
  counters: Record<string, number>;
  recentErrors: RecentErrorEntry[];
}

// Admin Subscription Grant types
export interface AdminSubscriptionGrant {
  id: string;
  user_id: string;
  user_email: string;
  user_phone: string;
  granted_by_user_id: string | null;
  granted_by_email: string;
  reason: string;
  is_active: boolean;
  granted_at: string | null;
  revoked_at: string | null;
  revoked_by_user_id: string | null;
  revoked_by_email: string;
}

export interface AdminSubscriptionGrantAuditLog {
  id: string;
  target_user_id: string;
  target_email: string;
  action: 'grant' | 'revoke';
  admin_user_id: string | null;
  admin_email: string;
  reason: string;
  created_at: string | null;
}

export interface AdminSkillCallSummary {
  id: string;
  conversation_id: string;
  message_id: string;
  skill_id: string;
  input: Record<string, unknown>;
  state: string;
  started_at: string;
  ended_at: string;
  duration_ms: number | null;
}

export interface AdminSkillCallDetail extends AdminSkillCallSummary {
  run_id: string;
  streamed_text: string;
  output: unknown[];
  error: string;
  created_at: string;
}

export interface AdminUser {
  id: string;
  email: string;
  phone_number: string;
  name: string;
  auth_provider: string;
  created_at: string;
  last_login_at: string;
}

export interface AdminUsersResponse {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminSubscriptionUserSearchResult {
  id: string;
  email: string;
  phone_number: string;
  created_at: string | null;
  has_admin_grant: boolean;
}

// Prompts types
export interface PromptEntry {
  slug: string;
  name: string;
  content: string;
  description: string;
  category: string;
  createdAt: string;
  updatedAt: string;
}

export interface AdminTokenUsageSummary {
  spendInr: number;
  inputTokens: number;
  outputTokens: number;
  callsCount: number;
  unknownPricedCalls: number;
  usersCount: number;
  overallSpendInr: number;
  overallInputTokens: number;
  overallOutputTokens: number;
  overallCallsCount: number;
  unlinkedSpendInr: number;
  unlinkedCallsCount: number;
}

export interface AdminTokenUsageUser {
  userId: string;
  email: string;
  phoneNumber: string;
  spendInr: number;
  inputTokens: number;
  outputTokens: number;
  callsCount: number;
}

export interface AdminTokenUsageConversation {
  conversationId: string;
  spendInr: number;
  inputTokens: number;
  outputTokens: number;
  callsCount: number;
  lastUsedAt: string;
}

export interface AdminTokenUsageCall {
  messageId: string;
  stage: string;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  costInr: number | null;
  createdAt: string;
}

