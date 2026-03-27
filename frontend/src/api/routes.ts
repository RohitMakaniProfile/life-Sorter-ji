export const API_ROUTES = {
  auth: {
    me: '/api/v1/auth/me',
    google: '/api/v1/auth/google',
    sendOtp: '/api/v1/auth/send-otp',
    verifyOtp: '/api/v1/auth/verify-otp',
  },
  agent: {
    session: '/api/v1/agent/session',
    sessionById: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}`,
    patchSession: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}`,
    advanceSession: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}/advance`,
    sessionStatus: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}/status`,
    websiteSnapshot: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}/website-snapshot`,
    contextPool: (sid: string) => `/api/v1/agent/session/${encodeURIComponent(sid)}/context-pool`,
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
    plan: '/api/chat/plan',
    planStream: '/api/chat/plan/stream',
    planApproveStream: '/api/chat/plan/approve/stream',
    stream: '/api/chat/stream',
    message: '/api/chat/message',
    messages: '/api/chat/messages',
    conversations: '/api/chat/conversations',
    conversationById: (id: string) => `/api/chat/conversations/${encodeURIComponent(id)}`,
    skills: '/api/chat/skills',
    skillCalls: '/api/chat/skill-calls',
    tokenUsage: '/api/chat/token-usage',
  },
  agents: {
    base: '/api/agents',
    byId: (id: string) => `/api/agents/${encodeURIComponent(id)}`,
  },
} as const;

