import { API_ROUTES } from '../../api/routes';
import { apiPost } from '../../api/http';
import { coreApi } from '../../api/services/core';

// ─── Session ──────────────────────────────────────────────────────
export const createSession = () => apiPost(API_ROUTES.agent.session, {});

// ─── Q1 → Q2 → Q3 ───────────────────────────────────────────────
export const submitOutcome = (sessionId, outcome, outcomeLabel) =>
  coreApi.patchAgentSession(sessionId, { outcome, outcome_label: outcomeLabel });

export const submitDomain = (sessionId, domain) =>
  coreApi.patchAgentSession(sessionId, { domain });

export const submitTask = (sessionId, task) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'task_setup', task })
    .then((res) => res?.result ?? res);

// ─── URL & Crawl ─────────────────────────────────────────────────
export const submitUrl = (sessionId, businessUrl, gbpUrl = '') =>
  coreApi.patchAgentSession(sessionId, { business_url: businessUrl, gbp_url: gbpUrl }).then((snapshot) => ({
    ...snapshot,
    crawl_started: snapshot?.crawl_status === 'in_progress',
  }));

export const skipUrl = (sessionId) =>
  coreApi.patchAgentSession(sessionId, { skip_url: true });

export const getCrawlStatus = (sessionId) =>
  coreApi.getAgentSessionView(sessionId, 'status');

// ─── Scale Questions ──────────────────────────────────────────────
export const getScaleQuestions = (sessionId) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'scale_questions' })
    .then((res) => res?.result ?? res);

export const submitScaleAnswers = (sessionId, answers) =>
  coreApi.patchAgentSession(sessionId, { scale_answers: answers });

// ─── Diagnostic / RCA ─────────────────────────────────────────────
export const startDiagnostic = (sessionId) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'start_diagnostic' })
    .then((res) => res?.result ?? res);

export const submitAnswer = (sessionId, questionIndex, answer) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'submit_answer', question_index: questionIndex, answer })
    .then((res) => res?.result ?? res);

// ─── Precision & Recommendations ──────────────────────────────────
export const getPrecisionQuestions = (sessionId) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'precision_questions' })
    .then((res) => res?.result ?? res);

export const getRecommendations = (sessionId) =>
  coreApi
    .advanceAgentSession(sessionId, { action: 'recommend' })
    .then((res) => res?.result ?? res);
