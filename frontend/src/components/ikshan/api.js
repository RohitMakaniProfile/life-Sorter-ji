const API_BASE = import.meta.env.VITE_API_URL || '';
const S = '/api/v1/agent/session';

// ─── Helper: JSON POST ────────────────────────────────────────────
async function post(path, body = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

async function get(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

// ─── Session ──────────────────────────────────────────────────────
export const createSession = () => post(`${S}`);

// ─── Q1 → Q2 → Q3 ───────────────────────────────────────────────
export const submitOutcome = (sessionId, outcome, outcomeLabel) =>
  post(`${S}/outcome`, { session_id: sessionId, outcome, outcome_label: outcomeLabel });

export const submitDomain = (sessionId, domain) =>
  post(`${S}/domain`, { session_id: sessionId, domain });

export const submitTask = (sessionId, task) =>
  post(`${S}/task`, { session_id: sessionId, task });

// ─── URL & Crawl ─────────────────────────────────────────────────
export const submitUrl = (sessionId, businessUrl, gbpUrl = '') =>
  post(`${S}/url`, { session_id: sessionId, business_url: businessUrl, gbp_url: gbpUrl });

export const skipUrl = (sessionId) =>
  post(`${S}/skip-url`, { session_id: sessionId });

export const getCrawlStatus = (sessionId) =>
  get(`${S}/${sessionId}/crawl-status`);

// ─── Scale Questions ──────────────────────────────────────────────
export const getScaleQuestions = (sessionId) =>
  get(`${S}/${sessionId}/scale-questions`);

export const submitScaleAnswers = (sessionId, answers) =>
  post(`${S}/scale-answers`, { session_id: sessionId, answers });

// ─── Diagnostic / RCA ─────────────────────────────────────────────
export const startDiagnostic = (sessionId) =>
  post(`${S}/start-diagnostic`, { session_id: sessionId });

export const submitAnswer = (sessionId, questionIndex, answer) =>
  post(`${S}/answer`, { session_id: sessionId, question_index: questionIndex, answer });

// ─── Precision & Recommendations ──────────────────────────────────
export const getPrecisionQuestions = (sessionId) =>
  post(`${S}/precision-questions`, { session_id: sessionId });

export const getRecommendations = (sessionId) =>
  post(`${S}/recommend`, { session_id: sessionId });
