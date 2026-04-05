export const API_ROUTES = {
  auth: {
    me: '/api/v1/auth/me',
    google: '/api/v1/auth/google',
    googleExchange: '/api/v1/auth/google/exchange',
    sendOtp: '/api/v1/auth/send-otp',
    verifyOtp: '/api/v1/auth/verify-otp',
    // For linking phone/email to existing user
    linkPhone: '/api/v1/auth/verify-otp',  // same endpoint, but with link_to_user_id
    linkEmail: '/api/v1/auth/google/exchange',  // same endpoint, but with link_to_user_id
  },
  admin: {
    management: {
      observability: '/api/v1/admin/management/observability',
      config: '/api/v1/admin/management/config',
      configByKey: (key: string) => `/api/v1/admin/management/config/${encodeURIComponent(key)}`,
      deleteUser: (userId: string) => `/api/v1/admin/management/users/${encodeURIComponent(userId)}`,
      userSkillCalls: (userId: string, limit?: number, offset?: number) => {
        const params = new URLSearchParams();
        if (limit != null) params.set('limit', String(limit));
        if (offset != null) params.set('offset', String(offset));
        const qs = params.toString();
        return `/api/v1/admin/management/users/${encodeURIComponent(userId)}/skill-calls${qs ? `?${qs}` : ''}`;
      },
      skillCallDetail: (id: string) => `/api/v1/admin/management/skill-calls/${encodeURIComponent(id)}`,
      users: (q?: string, limit?: number, offset?: number) => {
        const params = new URLSearchParams();
        if (q) params.set('q', q);
        if (limit != null) params.set('limit', String(limit));
        if (offset != null) params.set('offset', String(offset));
        const qs = params.toString();
        return `/api/v1/admin/management/users${qs ? `?${qs}` : ''}`;
      },
    },
    subscriptionGrants: {
      list: '/api/v1/admin/subscription-grants',
      auditLog: '/api/v1/admin/subscription-grants/audit-log',
      searchUsers: (q: string) => `/api/v1/admin/subscription-grants/search-users?q=${encodeURIComponent(q)}`,
      grant: '/api/v1/admin/subscription-grants/grant',
      revoke: '/api/v1/admin/subscription-grants/revoke',
    },
  },
  onboarding: {
    upsert: '/api/v1/onboarding',
    state: (sessionId?: string | null, userId?: string | null) => {
      const params = new URLSearchParams();
      if (sessionId) params.append('session_id', sessionId);
      if (userId) params.append('user_id', userId);
      return `/api/v1/onboarding/state?${params.toString()}`;
    },
    toolsByQ1Q2Q3: '/api/v1/onboarding/tools/by-q1-q2-q3',
    rcaNextQuestion: '/api/v1/onboarding/rca-next-question',
    precisionStart: '/api/v1/onboarding/precision/start',
    precisionAnswer: '/api/v1/onboarding/precision/answer',
    playbookLaunch: '/api/v1/onboarding/playbook/launch',
    playbookGapAnswers: '/api/v1/onboarding/playbook/gap-answers',
  },
  aiChat: {
    stream: '/api/v1/ai-chat/stream',
    message: '/api/v1/ai-chat/message',
    messageBackground: '/api/v1/ai-chat/message/background',
    messages: '/api/v1/ai-chat/messages',
    conversations: '/api/v1/ai-chat/conversations',
    newConversation: '/api/v1/ai-chat/conversations',
    conversationById: (id: string) => `/api/v1/ai-chat/conversations/${encodeURIComponent(id)}`,
    skills: '/api/v1/ai-chat/skills',
    skillCalls: '/api/v1/ai-chat/skill-calls',
    tokenUsage: '/api/v1/ai-chat/token-usage',
    insightFeedback: '/api/v1/ai-chat/insight-feedback',
    planStatus: '/api/v1/ai-chat/plan-status',
    planExecute: '/api/v1/ai-chat/plan-execute',
    agentAccess: '/api/v1/ai-chat/agent-access',
  },
  agents: {
    base: '/api/agents',
    byId: (id: string) => `/api/agents/${encodeURIComponent(id)}`,
  },

  payments: {
    createOrder: '/api/v1/payments/create-order',
    callback: '/api/v1/payments/callback',
    complete: '/api/v1/payments/complete',
    entitlements: '/api/v1/payments/entitlements',
    status: (orderId: string) =>
      `/api/v1/payments/status/${encodeURIComponent(orderId)}`,
  },

  plans: {
    list: '/api/v1/plans',
  },

  taskStream: {
    start: (taskType: string) => `/api/v1/task-stream/start/${encodeURIComponent(taskType)}`,
    eventsByStreamId: (streamId: string) => `/api/v1/task-stream/events/${encodeURIComponent(streamId)}`,
    eventsByActor: (taskType: string) => `/api/v1/task-stream/events/${encodeURIComponent(taskType)}/resume`,
    statusByStreamId: (streamId: string) => `/api/v1/task-stream/status/${encodeURIComponent(streamId)}`,
    // Plan execution via task stream (replaces polling)
    planExecute: '/api/v1/task-stream/start/plan%2Fexecute',
  },
} as const;

