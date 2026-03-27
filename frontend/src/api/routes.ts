export const API_ROUTES = {
  auth: {
    me: '/api/v1/auth/me',
    google: '/api/v1/auth/google',
    sendOtp: '/api/v1/auth/send-otp',
    verifyOtp: '/api/v1/auth/verify-otp',
  },
  agent: {
    session: '/api/v1/agent/session',
    sessionById: (sid: string, view?: 'summary' | 'status' | 'context_pool' | 'website_snapshot') =>
      `/api/v1/agent/session/${encodeURIComponent(sid)}${view ? `?view=${encodeURIComponent(view)}` : ''}`,
    patchSession: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}`,
    advanceSession: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}/advance`,
  },
  playbook: {
    start: '/api/v1/playbook/start',
    generate: '/api/v1/playbook/generate',
    gapAnswers: '/api/v1/playbook/gap-answers',
  },
  payments: {
    createOrder: '/api/v1/payments/create-order',
    status: (orderId: string) => `/api/v1/payments/status/${encodeURIComponent(orderId)}`,
  },
  legacy: {
    saveIdea: '/api/save-idea',
    chat: '/api/chat',
    searchCompanies: '/api/search-companies',
    marketIntelligence: '/api/market-intelligence',
  },
  aiChat: {
    stream: '/api/v1/ai-chat/stream',
    message: '/api/v1/ai-chat/message',
    messages: '/api/v1/ai-chat/messages',
    conversations: '/api/v1/ai-chat/conversations',
    conversationById: (id: string) => `/api/v1/ai-chat/conversations/${encodeURIComponent(id)}`,
    skills: '/api/v1/ai-chat/skills',
    skillCalls: '/api/v1/ai-chat/skill-calls',
    tokenUsage: '/api/v1/ai-chat/token-usage',
  },
  agents: {
    base: '/api/agents',
    byId: (id: string) => `/api/agents/${encodeURIComponent(id)}`,
  },
} as const;

