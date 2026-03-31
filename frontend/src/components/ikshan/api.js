import { API_ROUTES } from '../../api/routes';
import { apiGet, apiPost } from '../../api/http';

// ─── Session ──────────────────────────────────────────────────────
export const createSession = () => apiPost(API_ROUTES.agent.session, {});

// ─── Q1 → Q2 → Q3 ───────────────────────────────────────────────
export const submitOutcome = (sessionId, outcome, outcomeLabel) =>
  apiPost(API_ROUTES.agent.outcome, { session_id: sessionId, outcome, outcome_label: outcomeLabel });

export const submitDomain = (sessionId, domain) =>
  apiPost(API_ROUTES.agent.domain, { session_id: sessionId, domain });

export const submitTask = (sessionId, task) =>
  apiPost(API_ROUTES.agent.task, { session_id: sessionId, task });

// ─── URL & Crawl ─────────────────────────────────────────────────
export const submitUrl = (sessionId, businessUrl, gbpUrl = '') =>
  apiPost(API_ROUTES.agent.url, { session_id: sessionId, business_url: businessUrl, gbp_url: gbpUrl });

export const skipUrl = (sessionId) =>
  apiPost(API_ROUTES.agent.skipUrl, { session_id: sessionId });

export const getCrawlStatus = (sessionId) =>
  apiGet(API_ROUTES.agent.crawlStatus(sessionId));

// ─── Scale Questions ──────────────────────────────────────────────
export const getScaleQuestions = (sessionId) =>
  apiGet(API_ROUTES.agent.scaleQuestions(sessionId));

export const submitScaleAnswers = (sessionId, answers) =>
  apiPost(API_ROUTES.agent.scaleAnswers, { session_id: sessionId, answers });

// ─── Diagnostic / RCA ─────────────────────────────────────────────
export const startDiagnostic = (sessionId) =>
  apiPost(API_ROUTES.agent.startDiagnostic, { session_id: sessionId });

export const submitAnswer = (sessionId, questionIndex, answer) =>
  apiPost(API_ROUTES.agent.answer, { session_id: sessionId, question_index: questionIndex, answer });

// ─── Precision & Recommendations ──────────────────────────────────
export const getPrecisionQuestions = (sessionId) =>
  apiPost(API_ROUTES.agent.precisionQuestions, { session_id: sessionId });

export const getRecommendations = (sessionId) =>
  apiPost(API_ROUTES.agent.recommend, { session_id: sessionId });
