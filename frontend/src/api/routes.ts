export const API_ROUTES = {
  auth: {
    me: '/api/v1/auth/me',
    google: '/api/v1/auth/google',
    googleExchange: '/api/v1/auth/google/exchange',
    sendOtp: '/api/v1/auth/send-otp',
    verifyOtp: '/api/v1/auth/verify-otp',
  },
  onboarding: {
    upsert: '/api/v1/onboarding',
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
    conversationById: (id: string) => `/api/v1/ai-chat/conversations/${encodeURIComponent(id)}`,
    skills: '/api/v1/ai-chat/skills',
    skillCalls: '/api/v1/ai-chat/skill-calls',
    tokenUsage: '/api/v1/ai-chat/token-usage',
    insightFeedback: '/api/v1/ai-chat/insight-feedback',
    planStatus: '/api/v1/ai-chat/plan-status',
  },
  agents: {
    base: '/api/agents',
    byId: (id: string) => `/api/agents/${encodeURIComponent(id)}`,
  },

  taskStream: {
    start: (taskType: string) => `/api/v1/task-stream/start/${encodeURIComponent(taskType)}`,
    eventsByStreamId: (streamId: string) => `/api/v1/task-stream/events/${encodeURIComponent(streamId)}`,
    eventsByActor: (taskType: string) => `/api/v1/task-stream/events/${encodeURIComponent(taskType)}/resume`,
    statusByStreamId: (streamId: string) => `/api/v1/task-stream/status/${encodeURIComponent(streamId)}`,
  },
} as const;

