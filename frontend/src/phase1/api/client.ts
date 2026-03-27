/**
 * Phase 1 API Client
 * ------------------
 * Typed wrappers for every backend endpoint called by ChatBotNew / ChatBotNewMobile.
 *
 * Usage:
 *   import { createSession, setOutcome, submitAnswer } from '../phase1/api/client';
 *
 * Base URL comes from VITE_API_URL (frontend/.env).
 * All functions throw on non-2xx responses.
 */

import { getApiBaseRequired } from '../../config/apiBase';

// ─────────────────────────────────────────────────────────────────────────────
// Core fetch helper
// ─────────────────────────────────────────────────────────────────────────────

function getBase(): string {
  return getApiBaseRequired();
}

async function phase1Fetch(path: string, options: RequestInit = {}): Promise<Response> {
  return fetch(`${getBase()}${path}`, options);
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared types
// ─────────────────────────────────────────────────────────────────────────────

export interface DynamicQuestion {
  question: string;
  options: string[];
  allows_free_text: boolean;
  section: string;
  section_label: string;
  insight: string;
}

export interface EarlyRecommendation {
  name: string;
  description: string;
  url: string | null;
  category: 'extension' | 'gpt' | 'company';
  rating: string | null;
  why_relevant: string;
}

export interface ToolRecommendation {
  name: string;
  description: string;
  url: string | null;
  category: 'extension' | 'gpt' | 'company';
  free: boolean | null;
  rating: string | null;
  why_recommended: string;
  implementation_stage: string;
  issue_solved: string;
  ease_of_use: string;
}

export interface CrawlSummary {
  points: string[];
  crawl_status: string;
  completed_at: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// SESSION — /api/v1/agent/session
// ─────────────────────────────────────────────────────────────────────────────

/** POST /api/v1/agent/session — create a new session */
export async function createSession(): Promise<{ session_id: string; stage: string }> {
  const res = await phase1Fetch('/api/v1/agent/session', { method: 'POST' });
  if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Q1 / Q2 / Q3 — outcome, domain, task
// ─────────────────────────────────────────────────────────────────────────────

/** POST /api/v1/agent/session/outcome — record Q1 (growth bucket) */
export async function setOutcome(
  session_id: string,
  outcome: string,
  outcome_label: string
): Promise<{ session_id: string; stage: string }> {
  const res = await phase1Fetch('/api/v1/agent/session/outcome', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, outcome, outcome_label }),
  });
  if (!res.ok) throw new Error(`setOutcome failed: ${res.status}`);
  return res.json();
}

/** POST /api/v1/agent/session/domain — record Q2 (sub-category) */
export async function setDomain(
  session_id: string,
  domain: string
): Promise<{ session_id: string; stage: string }> {
  const res = await phase1Fetch('/api/v1/agent/session/domain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, domain }),
  });
  if (!res.ok) throw new Error(`setDomain failed: ${res.status}`);
  return res.json();
}

export interface SetTaskResponse {
  session_id: string;
  stage: string;
  persona_loaded: string;
  task_matched: string;
  rca_mode: boolean;
  acknowledgment: string;
  insight: string;
  questions: DynamicQuestion[];
  early_recommendations: EarlyRecommendation[];
  early_recommendations_message: string;
}

/** POST /api/v1/agent/session/task — record Q3, returns first RCA question + early recs */
export async function setTask(session_id: string, task: string): Promise<SetTaskResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/task', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, task }),
  });
  if (!res.ok) throw new Error(`setTask failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// RCA DIAGNOSTIC ANSWERS
// ─────────────────────────────────────────────────────────────────────────────

export interface SubmitAnswerResponse {
  session_id: string;
  all_answered: boolean;
  rca_mode: boolean;
  next_question: DynamicQuestion | null;
  acknowledgment: string;
  rca_summary: string;  // populated when all_answered = true
  insight: string;
}

/** POST /api/v1/agent/session/answer — submit one RCA answer, get next question from Claude */
export async function submitAnswer(
  session_id: string,
  question_index: number,
  answer: string
): Promise<SubmitAnswerResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, question_index, answer }),
  });
  if (!res.ok) throw new Error(`submitAnswer failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// WEBSITE AUDIENCE ANALYSIS — older flow, still active in some paths
// ─────────────────────────────────────────────────────────────────────────────

export interface AudienceInsights {
  intended_audience: string;
  actual_audience: string;
  mismatch_analysis: string;
  recommendations: string[];
}

export interface WebsiteAudienceResponse {
  session_id: string;
  website_url: string;
  url_type: 'website' | 'social_profile' | 'gbp';
  audience_insights: AudienceInsights;
  business_summary: string;
  analysis_note: string;
}

/**
 * POST /api/v1/agent/session/website
 * Submits a single website URL and returns audience analysis (GPT-powered).
 * Different from submitBusinessUrl — this does NOT trigger the Playwright crawl.
 * Returns audience_insights synchronously.
 */
export async function submitWebsiteForAnalysis(
  session_id: string,
  website_url: string
): Promise<WebsiteAudienceResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/website', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, website_url }),
  });
  if (!res.ok) throw new Error(`submitWebsiteForAnalysis failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// BUSINESS URL SUBMISSION — triggers async Playwright crawl
// ─────────────────────────────────────────────────────────────────────────────

export interface SubmitUrlResponse {
  session_id: string;
  business_url: string;
  gbp_url: string;
  url_type: string;
  crawl_started: boolean;
  gbp_crawl_started: boolean;
  message: string;
}

/**
 * POST /api/v1/agent/session/url
 * Submit website + optional Google Business Profile URL.
 * Triggers an async Playwright crawl in the background.
 * Poll crawl status with getCrawlStatus().
 */
export async function submitBusinessUrl(
  session_id: string,
  business_url: string,
  gbp_url: string = ''
): Promise<SubmitUrlResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, business_url, gbp_url }),
  });
  if (!res.ok) throw new Error(`submitBusinessUrl failed: ${res.status}`);
  return res.json();
}

/**
 * POST /api/v1/agent/session/skip-url — fire-and-forget when user skips URL input.
 * Tells backend no crawl data will be available.
 */
export async function skipUrl(session_id: string): Promise<void> {
  // Fire-and-forget — intentionally not awaited in UI, but exposed typed here
  await phase1Fetch('/api/v1/agent/session/skip-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// CRAWL STATUS POLLING
// ─────────────────────────────────────────────────────────────────────────────

export interface CrawlStatusResponse {
  crawl_status: '' | 'in_progress' | 'complete' | 'failed';
  crawl_summary: CrawlSummary | null;
  crawl_progress: {
    pages_found: number;
    pages_crawled: number;
    current_page: string;
    phase: string;
  };
}

/**
 * GET /api/v1/agent/session/{session_id}/crawl-status
 * Poll every 3s until crawl_status = "complete" | "failed".
 */
export async function getCrawlStatus(session_id: string): Promise<CrawlStatusResponse> {
  const res = await phase1Fetch(`/api/v1/agent/session/${session_id}/crawl-status`);
  if (!res.ok) throw new Error(`getCrawlStatus failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// SCALE QUESTIONS — business context form (between URL and RCA diagnostic)
// ─────────────────────────────────────────────────────────────────────────────

export interface ScaleQuestion {
  id: string;
  icon: string;
  question: string;
  options: string[];
  multiSelect: boolean;
}

/** GET /api/v1/agent/session/{session_id}/scale-questions */
export async function getScaleQuestions(
  session_id: string
): Promise<{ questions: ScaleQuestion[] }> {
  const res = await phase1Fetch(`/api/v1/agent/session/${session_id}/scale-questions`);
  if (!res.ok) throw new Error(`getScaleQuestions failed: ${res.status}`);
  return res.json();
}

/** POST /api/v1/agent/session/scale-answers — submit all scale form answers at once */
export async function submitScaleAnswers(
  session_id: string,
  answers: Record<string, string | string[]>
): Promise<{ session_id: string; stage: string }> {
  const res = await phase1Fetch('/api/v1/agent/session/scale-answers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, answers }),
  });
  if (!res.ok) throw new Error(`submitScaleAnswers failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// START DIAGNOSTIC — context-aware first RCA question after scale questions
// ─────────────────────────────────────────────────────────────────────────────

export interface StartDiagnosticResponse {
  session_id: string;
  rca_mode: boolean;
  question: DynamicQuestion | null;
  insight: string;
}

/**
 * POST /api/v1/agent/session/start-diagnostic
 * Called after scale answers are submitted.
 * Returns a context-aware first RCA question that factors in crawl data + scale answers.
 */
export async function startDiagnostic(session_id: string): Promise<StartDiagnosticResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/start-diagnostic', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
  if (!res.ok) throw new Error(`startDiagnostic failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// PRECISION QUESTIONS — cross-referenced Qs after RCA is complete
// ─────────────────────────────────────────────────────────────────────────────

export interface PrecisionQuestion {
  type: string;
  question: string;
  options: string[];
  allows_free_text: boolean;
  section_label: string;
  insight: string;
}

export interface PrecisionQuestionsResponse {
  session_id: string;
  available: boolean;
  questions: PrecisionQuestion[];
}

/**
 * POST /api/v1/agent/session/precision-questions
 * Called after RCA all_answered = true.
 * Returns targeted questions based on RCA + crawl data cross-reference.
 * If available = false, skip directly to playbook.
 */
export async function getPrecisionQuestions(
  session_id: string
): Promise<PrecisionQuestionsResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/precision-questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
  if (!res.ok) throw new Error(`getPrecisionQuestions failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// FINAL RECOMMENDATIONS
// ─────────────────────────────────────────────────────────────────────────────

export interface RecommendationsResponse {
  session_id: string;
  extensions: ToolRecommendation[];
  gpts: ToolRecommendation[];
  companies: ToolRecommendation[];
  summary: string | { one_liner: string; [key: string]: unknown };
  rca_summary: string;
  rca_handoff: string;
}

/** POST /api/v1/agent/session/recommend — generate final personalised tool recommendations */
export async function getRecommendations(session_id: string): Promise<RecommendationsResponse> {
  const res = await phase1Fetch('/api/v1/agent/session/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
  if (!res.ok) throw new Error(`getRecommendations failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// WEBSITE SNAPSHOT — lightweight preview shown while playbook generates
// ─────────────────────────────────────────────────────────────────────────────

export interface WebsiteSnapshot {
  available: boolean;
  url: string;
  title: string;
  description: string;
  h1: string;
  screenshot_url: string | null;
  tech_signals: string[];
  pages_crawled: number;
}

/**
 * GET /api/v1/agent/session/{session_id}/website-snapshot
 * Fire-and-forget — only show result if available = true.
 * Called just before /playbook/generate starts.
 */
export async function getWebsiteSnapshot(session_id: string): Promise<WebsiteSnapshot> {
  const res = await phase1Fetch(`/api/v1/agent/session/${session_id}/website-snapshot`);
  if (!res.ok) throw new Error(`getWebsiteSnapshot failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// PLAYBOOK PIPELINE
// ─────────────────────────────────────────────────────────────────────────────

export interface GapQuestionParsed {
  id: string;       // e.g. "Q1"
  label: string;
  question: string;
  options: string[]; // e.g. ["A) ...", "B) ..."]
}

export interface StartPlaybookResponse {
  session_id: string;
  stage: 'gap_questions' | 'ready';
  gap_questions: string;
  gap_questions_parsed: GapQuestionParsed[];
  agent1_output: string;
  agent2_output: string;
  message: string;
}

/**
 * POST /api/v1/playbook/start
 * Runs Agent 1 (Context Brief) + Agent 2 (ICP Card).
 * If stage = "gap_questions" → show gap Q UI before calling generatePlaybook().
 * If stage = "ready" → call generatePlaybook() directly.
 */
export async function startPlaybook(session_id: string): Promise<StartPlaybookResponse> {
  const res = await phase1Fetch('/api/v1/playbook/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `startPlaybook failed: ${res.status}`);
  }
  return res.json();
}

/**
 * POST /api/v1/playbook/gap-answers
 * Submit user's gap question answers (e.g. "Q1: A, Q2: C").
 * Call generatePlaybook() after this.
 */
export async function submitGapAnswers(
  session_id: string,
  answers: string
): Promise<{ session_id: string; stage: string; message: string }> {
  const res = await phase1Fetch('/api/v1/playbook/gap-answers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, answers }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `submitGapAnswers failed: ${res.status}`);
  }
  return res.json();
}

export interface GeneratePlaybookResponse {
  session_id: string;
  context_brief: string;  // Agent A output
  icp_card: string;        // Agent A ICP portion
  playbook: string;        // Agent C — 10-step growth plan
  website_audit: string;   // Agent E — scored website audit
  latencies: Record<string, number>;
}

/**
 * POST /api/v1/playbook/generate
 * Runs Agent C (10-step playbook) + Agent E (website audit) and returns all outputs.
 * Pass gap_answers if calling after gap-answers path, omit otherwise.
 */
export async function generatePlaybook(
  session_id: string,
  gap_answers?: string
): Promise<GeneratePlaybookResponse> {
  const res = await phase1Fetch('/api/v1/playbook/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(gap_answers ? { session_id, gap_answers } : { session_id }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(body.detail ?? `generatePlaybook failed: ${res.status}`);
  }
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// AUTH — OTP + Google Sign-In
// ─────────────────────────────────────────────────────────────────────────────

/** POST /api/v1/auth/send-otp */
export async function sendOtp(
  session_id: string,
  phone_number: string
): Promise<{ success: boolean; message: string; otp_session_id: string }> {
  const res = await phase1Fetch('/api/v1/auth/send-otp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, phone_number }),
  });
  if (!res.ok) throw new Error(`sendOtp failed: ${res.status}`);
  return res.json();
}

/** POST /api/v1/auth/verify-otp */
export async function verifyOtp(
  session_id: string,
  otp_session_id: string,
  otp_code: string
): Promise<{ success: boolean; verified: boolean; message: string }> {
  const res = await phase1Fetch('/api/v1/auth/verify-otp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id, otp_session_id, otp_code }),
  });
  if (!res.ok) throw new Error(`verifyOtp failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// PAYMENTS — JusPay
// ─────────────────────────────────────────────────────────────────────────────

export interface CreateOrderRequest {
  amount: number;
  customer_id: string;
  customer_email?: string;
  customer_phone?: string;
  return_url?: string;
  description?: string;
  udf1?: string;
  udf2?: string;
}

export interface CreateOrderResponse {
  success: boolean;
  order_id: string;
  client_auth_token: string;
  status: string;
  payment_links: Record<string, string>;
  sdk_payload: Record<string, unknown>;
  error?: string;
}

/** POST /api/v1/payments/create-order */
export async function createOrder(payload: CreateOrderRequest): Promise<CreateOrderResponse> {
  const res = await fetch('/api/v1/payments/create-order', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`createOrder failed: ${res.status}`);
  return res.json();
}

export interface PaymentStatusResponse {
  success: boolean;
  order_id: string;
  status: string;
  amount: number;
  currency: string;
  customer_id: string;
  txn_id: string | null;
  payment_method: string | null;
  payment_method_type: string | null;
  refunds: unknown[];
  error?: string;
}

/** GET /api/v1/payments/status/{orderId} */
export async function getPaymentStatus(orderId: string): Promise<PaymentStatusResponse> {
  const res = await fetch(`/api/v1/payments/status/${orderId}`);
  if (!res.ok) throw new Error(`getPaymentStatus failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPANIES — AI-powered search
// ─────────────────────────────────────────────────────────────────────────────

export interface CompanySearchRequest {
  domain?: string;
  subdomain?: string;
  requirement?: string;
  goal?: string;
  role?: string;
  userContext?: {
    goal?: string;
    domain?: string;
    category?: string;
    role?: string;
    businessType?: string;
    industry?: string;
    targetAudience?: string;
    marketSegment?: string;
  };
}

export interface Company {
  name: string;
  country: string;
  problem: string;
  description: string;
  differentiator: string;
  aiAdvantage: string;
  fundingAmount: string;
  fundingDate: string;
  pricing: string;
  domain: string;
  rowNumber: number;
  matchScore?: number;
  matchReason?: string;
}

export interface CompanySearchResponse {
  success: boolean;
  companies: Company[];
  alternatives: Company[];
  totalCount: number;
  searchMethod: string;
  helpfulResponse: string;
  userRequirement: string;
  message: string;
  error?: string;
}

/**
 * POST /api/search-companies (legacy route — no /v1 prefix)
 * Called from the fallback solution stack flow.
 */
export async function searchCompanies(
  payload: CompanySearchRequest
): Promise<CompanySearchResponse> {
  const res = await fetch('/api/search-companies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`searchCompanies failed: ${res.status}`);
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// IDEA TRACKING — Google Sheets event log
// ─────────────────────────────────────────────────────────────────────────────

export interface SaveIdeaPayload {
  userMessage: string;
  botResponse?: string;
  timestamp?: string;
  userName?: string;
  userEmail?: string;
  domain?: string;
  subdomain?: string;
  requirement?: string;
}

/**
 * POST /api/save-idea (legacy route — no /v1 prefix)
 * Fires-and-forgets user interaction events to Google Sheets.
 * Non-critical — never block UX on this.
 */
export async function saveIdea(payload: SaveIdeaPayload): Promise<void> {
  await phase1Fetch('/api/save-idea', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
