# API Flow — Complete Frontend ↔ Backend Map
> Phase 1 (AI Agent Chatbot) + Phase 2 (Research Agent Pipeline)
> Base URL: `http://localhost:8000`
> Frontend reads this from `VITE_API_URL` in `frontend/.env`

---

## Quick Index

| Layer | What it is |
|-------|-----------|
| [Phase 1 — Session Flow](#phase-1--session-flow) | The main chatbot: Q1→Q2→Q3→RCA→Recs→Playbook |
| [Phase 1 — All API Calls](#phase-1--all-api-calls) | Every fetch() in ChatBotNew / ChatBotNewMobile |
| [Phase 2 — Research Agent](#phase-2--research-agent-pipeline) | Streaming skill-based research pipeline |
| [Supporting Routers](#supporting-routers) | Auth, Payments, Leads, Companies, TTS, RAG, Sandbox |
| [State: Where Data Lives](#state--where-data-lives) | Memory vs Supabase vs SQLite |
| [Backend File Structure](#backend-file-structure) | Every service, router, model |

---

## Phase 1 — Session Flow

This is the step-by-step lifecycle every user goes through in the main chatbot.

```
[User opens chat]
       │
       ▼
POST /api/v1/agent/session
  → Creates in-memory session, returns session_id
       │
       ▼
POST /api/v1/agent/session/outcome         ← Q1: Growth bucket
  body: { session_id, outcome, outcome_label }
       │
       ▼
POST /api/v1/agent/session/domain          ← Q2: Sub-category
  body: { session_id, domain }
       │
       ▼
POST /api/v1/agent/session/task            ← Q3: Task selection
  body: { session_id, task }
  ┌─ returns: early_recommendations (instant, Q1+Q2+Q3 match)
  └─ returns: first dynamic RCA question
       │
       ▼
POST /api/v1/agent/session/answer  × N    ← RCA diagnostic Qs
  body: { session_id, question_index, answer }
  └─ Claude adapts each next question based on previous answer
       │
       ▼
POST /api/v1/agent/session/website         ← Website URL submission
  body: { session_id, website_url }
  └─ triggers async Playwright crawl in background
       │
       ▼  (optional polling)
GET /api/v1/agent/session/{id}             ← Poll crawl_status
  until crawl_status = "complete"
       │
       ▼
POST /api/v1/agent/session/recommend       ← Final recommendations
  body: { session_id }
  └─ returns: extensions, gpts, companies, rca_summary
       │
       ▼
POST /api/v1/playbook/start                ← Playbook Phase 0 + Agent 1-2
  body: { session_id }
  └─ returns: gap_questions for user to answer
       │
       ▼
POST /api/v1/playbook/gap-answers          ← User submits gap answers
  body: { session_id, answers }
  └─ triggers Agent 3 (playbook) + Agent 5 (website audit) in background
       │
       ▼
GET /api/v1/playbook/{session_id}          ← Poll until complete=true
  └─ returns: playbook, website_audit, context_brief, icp_card, latencies
```

---

## Phase 1 — All API Calls

### Agent Router — `/api/v1/agent`

#### `POST /api/v1/agent/session`
Create a new session.

```
Request:  (no body)
Response: { session_id: string, stage: "outcome" }
```

---

#### `POST /api/v1/agent/session/outcome`
Record Q1 — growth bucket chosen by user.

```
Request:
  session_id:    string
  outcome:       string   e.g. "lead-generation"
  outcome_label: string   e.g. "Lead Generation (Marketing, SEO & Social)"

Response:
  session_id: string
  stage:      "domain"
```

---

#### `POST /api/v1/agent/session/domain`
Record Q2 — sub-category / domain.

```
Request:
  session_id: string
  domain:     string   e.g. "Content & Social Media"

Response:
  session_id: string
  stage:      "task"
```

---

#### `POST /api/v1/agent/session/task`
Record Q3 — specific task. Triggers early recommendations + first RCA question.

```
Request:
  session_id: string
  task:       string   e.g. "Generate social media posts captions & hooks"

Response:
  session_id:                    string
  stage:                         "dynamic_questions"
  persona_loaded:                string   (persona doc filename used)
  task_matched:                  string   (exact task text matched)
  rca_mode:                      boolean  (true = Claude adaptive, false = static fallback)
  acknowledgment:                string   (Claude's reaction to the task)
  insight:                       string   (teaching nugget for first question)

  questions: [                            (ALL static questions if not rca_mode)
    {
      question:        string
      options:         string[]
      allows_free_text: boolean
      section:         string   "problems" | "rca_bridge" | "opportunities"
      section_label:   string
      insight:         string
    }
  ]

  early_recommendations: [               (instant tool matches)
    {
      name:                 string
      description:          string
      url:                  string | null
      category:             string   "extension" | "gpt" | "company"
      rating:               string | null
      why_relevant:         string
      implementation_stage: string
      issue_solved:         string
      ease_of_use:          string
    }
  ]
  early_recommendations_message: string
```

---

#### `POST /api/v1/agent/session/answer`
Submit one RCA question answer. Claude generates next question adaptively.

```
Request:
  session_id:     string
  question_index: number
  answer:         string

Response:
  session_id:   string
  all_answered: boolean
  next_question: {           (null if all_answered = true)
    question:         string
    options:          string[]
    allows_free_text: boolean
    section:          string
    section_label:    string
    insight:          string
  } | null
  acknowledgment: string
  rca_summary:    string     (only when all_answered = true)
  insight:        string
```

---

#### `POST /api/v1/agent/session/website`
Submit website URL. Triggers async Playwright crawl + audience analysis.

```
Request:
  session_id:  string
  website_url: string

Response:
  session_id: string
  website_url: string
  url_type:   "website" | "social_profile" | "gbp"
  audience_insights: {
    intended_audience:  string
    actual_audience:    string
    mismatch_analysis:  string
    recommendations:    string[]
  }
  business_summary: string
  analysis_note:    string
```

---

#### `POST /api/v1/agent/session/recommend`
Generate final personalised tool recommendations using full RCA + crawl context.

```
Request:
  session_id: string

Response:
  session_id:  string
  extensions:  ToolRecommendation[]
  gpts:        ToolRecommendation[]
  companies:   ToolRecommendation[]
  summary:     string
  rca_summary: string
  rca_handoff: string

ToolRecommendation:
  name:                 string
  description:          string
  url:                  string | null
  category:             "extension" | "gpt" | "company"
  free:                 boolean | null
  rating:               string | null
  why_recommended:      string
  implementation_stage: string
  issue_solved:         string
  ease_of_use:          string
```

---

#### `GET /api/v1/agent/session/{session_id}`
Get full live session snapshot. Used to poll crawl_status.

```
Response:
  session_id:              string
  stage:                   SessionStage
  outcome:                 string | null
  outcome_label:           string | null
  domain:                  string | null
  task:                    string | null
  persona_doc:             string | null
  questions_answers:       { question, answer, question_type }[]
  dynamic_questions_progress: { asked: number, total: number }
  recommendations: {
    extensions:  ToolRecommendation[]
    gpts:        ToolRecommendation[]
    companies:   ToolRecommendation[]
  }
  website_url:             string | null
  url_type:                string | null
  audience_insights:       object
  crawl_status:            "" | "in_progress" | "complete" | "failed"
  crawl_summary:           object
  business_profile:        object
  scale_questions_complete: boolean
```

---

#### `GET /api/v1/agent/personas`
List all available persona domains for Q2 dropdown.

```
Response:
  personas: [
    { domain_id: string, domain_name: string, persona_doc: string, icon: string }
  ]
```

---

### Playbook Router — `/api/v1/playbook`

#### `POST /api/v1/playbook/start`
Kick off playbook. Runs Agent 1 (Context Brief) + Agent 2 (ICP Card). Returns gap questions.

```
Request:
  session_id: string

Response:
  session_id:   string
  stage:        "gap_questions" | "ready"
  gap_questions: string                (raw text)
  gap_questions_parsed: [
    {
      id:       string   e.g. "Q1"
      label:    string
      question: string
      options:  string[]   e.g. ["A) ...", "B) ..."]
    }
  ]
  agent1_output: string
  agent2_output: string
  message:       string
```

---

#### `POST /api/v1/playbook/gap-answers`
Submit user's answers to gap questions. Triggers Agent 3 (10-step playbook) + Agent 5 (website audit).

```
Request:
  session_id: string
  answers:    string   e.g. "Q1-A, Q2-C" or free text

Response:
  session_id: string
  stage:      "generating"
  message:    string
```

---

#### `GET /api/v1/playbook/{session_id}`
Poll for completion. Returns all 5 agent outputs when ready.

```
Response:
  session_id:    string
  complete:      boolean
  stage:         string
  playbook:      string   (Agent C — 10-step growth plan)
  website_audit: string   (Agent E — scored website audit)
  context_brief: string   (Agent A — full context summary)
  icp_card:      string   (Agent A — ICP profile)
  latencies:     { agent_a: ms, agent_c: ms, agent_e: ms, ... }
```

---

### Auth Router — `/api/v1/auth`

#### `POST /api/v1/auth/send-otp`
```
Request:  { session_id: string, phone_number: string (10-digit Indian) }
Response: { success: boolean, message: string, otp_session_id: string }
```

#### `POST /api/v1/auth/verify-otp`
```
Request:  { session_id: string, otp_session_id: string, otp_code: string }
Response: { success: boolean, verified: boolean, message: string }
```

#### `POST /api/v1/auth/google`
```
Request:  { session_id: string, google_id: string, email: string, name: string, avatar_url?: string }
Response: { success: boolean, message: string }
```

---

### Payments Router — `/api/v1/payments`

#### `POST /api/v1/payments/create-order`
```
Request:
  amount:          number   (INR, e.g. 1000.00)
  customer_id:     string
  customer_email?: string
  customer_phone?: string
  return_url?:     string
  description?:    string
  udf1?, udf2?:   string   (custom fields)

Response:
  success:           boolean
  order_id:          string
  client_auth_token: string   (valid 15 min, for JusPay SDK)
  status:            string
  payment_links:     object
  sdk_payload:       object
  error?:            string
```

#### `POST /api/v1/payments/verify-stage2`
```
Request:  { order_id: string }
Response: { verified: boolean, order_id: string, amount: number, txn_id: string, reason: string, status: string }
```

#### `GET /api/v1/payments/status/{order_id}`
```
Response: { success, order_id, status, amount, currency, customer_id, txn_id, payment_method, refunds }
```

#### `POST /api/v1/payments/webhook`
JusPay server-to-server callback. HMAC-SHA256 verified. No frontend call.

#### `POST /api/v1/payments/callback`
JusPay POST redirect. Redirects browser to `{FRONTEND_URL}?payment_status=X&order_id=Y`.

---

### Leads Router — `/api/v1/leads`
Permanent CRM records in Supabase. Not called from main chatbot UI directly.

#### `POST /api/v1/leads`
```
Request:
  name:                      string (required)
  email:                     string (required)
  domain?:                   string
  subdomain?:                string
  outcome_seeked?:           string
  individual_type?:          string
  persona?:                  string
  nature_of_business?:       string
  business_website?:         string
  manual_business_details?:  string
  problem_description?:      string
  micro_solutions_tried?:    boolean
  micro_solutions_details?:  string
  tech_competency_level?:    number (1–5, default 3)
  timeline_urgency?:         string
  problem_due_to_poor_management?: boolean
  ai_recommendations?:       object[]

Response: { success: boolean, data: object, error?: string }
```

#### `PATCH /api/v1/leads/{lead_id}`
Same fields as above (all optional) + `status?: string`.

#### `GET /api/v1/leads`
```
Query params: domain?, status?, individual_type?, limit? (default 50), offset? (default 0)
Response: { success: boolean, data: object[], count: number, error?: string }
```

#### `POST /api/v1/leads/{lead_id}/conversations`
```
Request:  { messages: object[], recommendations?: object[] }
Response: { success: boolean, data: object, error?: string }
```

---

### Companies Router — `/api/v1/companies`

#### `GET /api/v1/companies?domain=X`
```
Response: { success: boolean, count: number, companies: Company[], error?: string }
```

#### `POST /api/v1/companies/search`  (also available as legacy `POST /api/search-companies`)
```
Request:
  domain?:     string
  subdomain?:  string
  requirement?: string
  userContext?: {
    role, businessType, industry, targetAudience,
    marketSegment, roleAndIndustry, solutionFor,
    salaryContext, freelanceType, challenge
  }

Response:
  success:         boolean
  companies:       Company[]
  alternatives:    Company[]
  totalCount:      number
  searchMethod:    string
  helpfulResponse: string
  userRequirement: string
  message:         string
  error?:          string

Company shape:
  name, country, problem, description, differentiator,
  aiAdvantage, fundingAmount, fundingDate, pricing, domain,
  rowNumber, matchScore?, matchReason?
```

---

### Speak Router — `/api/v1/speak`

#### `POST /api/v1/speak`
```
Request:  { text: string, language: "en" | "hi" }
Response: MP3 binary stream
  Headers: Content-Type: audio/mpeg
           Content-Disposition: inline; filename=speech.mp3
```

---

### Recommendations Router — `/api/v1/recommendations`

#### `GET /api/v1/recommendations/extensions?category=X&goal=Y`
#### `GET /api/v1/recommendations/gpts?category=X&goal=Y&role=Z`
```
Response: { success: boolean, data: object[], count: number }
```

#### `GET /api/v1/recommendations/rca?outcome=X&persona=Y&category=Z`
```
Response: { success: boolean, stages: object[], data?: object }
```

#### `GET /api/v1/recommendations/categories?outcome=X&persona=Y`
```
Response: { success: boolean, categories: string[], count: number }
```

---

### Ideas Router — `/api/v1/ideas`  (also `POST /api/save-idea`)

#### `POST /api/v1/ideas`
Fires-and-forgets to Google Sheets webhook.
```
Request:
  timestamp?, userName?, userEmail?,
  domain?, subdomain?, requirement?,
  userMessage?, botResponse?,
  source?: string (default "Ikshan Website - New Flow")

Response: { success: boolean, message: string }
```

---

### RAG Router — `/api/v1/rag`

#### `POST /api/v1/rag/ingest?force=false`
Ingest tools from `matched_tools_by_persona.json` into Qdrant vector store.
```
Response: { status, tools_ingested, errors, ... }
```

#### `POST /api/v1/rag/search`
```
Request:  { query: string, top_k?: number, persona?, source?, category? }
Response: { success: boolean, tools: object[], count: number, query: string }
```

#### `POST /api/v1/rag/search/session`
Uses full session context to build the search query automatically.
```
Request:  { session_id: string, top_k?: number, source?: string }
Response: { success: boolean, tools: object[], count: number }
```

#### `GET /api/v1/rag/stats`
```
Response: { collection, points_count, vectors_count, status }
```

#### `DELETE /api/v1/rag/collection`
Wipes the entire Qdrant collection.

---

### Sandbox Router — `/api/v1/sandbox`
Developer-only testing panel. Full logging, no auth/payment gates.

#### `POST /api/v1/sandbox/login`
```
Request:  { id: "ikshan", password: "123" }
Response: { authenticated: boolean, token: string, message: string }
```

#### Test Endpoints (mirror agent flow with full logging)
```
POST /api/v1/sandbox/test/session
POST /api/v1/sandbox/test/outcome   body: { session_id, outcome, outcome_label }
POST /api/v1/sandbox/test/domain    body: { session_id, domain }
POST /api/v1/sandbox/test/task      body: { session_id, task }
POST /api/v1/sandbox/test/answer    body: { session_id, question_index, answer }
POST /api/v1/sandbox/test/recommend body: { session_id }
```

#### Log Endpoints
```
GET    /api/v1/sandbox/logs                           → { sessions, total_sessions }
GET    /api/v1/sandbox/logs/{session_id}              → full log bundle
GET    /api/v1/sandbox/logs/{session_id}/context      → live context snapshot
GET    /api/v1/sandbox/logs/export/{session_id}       → .txt download
GET    /api/v1/sandbox/logs/export-all/global         → .txt download (all sessions)
DELETE /api/v1/sandbox/logs                           → clears all logs
```

---

## Phase 2 — Research Agent Pipeline

Lives at `/api` (no `/v1`). Separate SQLite DB (`tools.db`). Streaming SSE-based.
Frontend client: `frontend/src/phase2/api/client.ts`

### Chat Endpoints

#### `POST /api/chat/stream` — Main streaming endpoint
```
Request:
  message:         string
  conversationId?: string
  agentId?:        string
  retryFromStage?: string
  stageOutputs?:   Record<string, string>

Response: SSE stream
  data: { token: "text" }
  data: { stage: "thinking"|"scraping"|"scripting"|"generating"|"merging"|"done", label: string, stageIndex: number }
  data: { progress: { stage, type, message, value?, unit?, meta? } }
  data: { done: true, conversationId, messageId, agentId, runId, model, durationMs, stageOutputs, outputFile }
  data: { error: "message", errorAtStage: string }
```

#### `POST /api/chat/plan/stream` — Create plan with streaming
```
Request:  { message, conversationId?, agentId?, cancelPlanId? }
Response: SSE stream (same format as /chat/stream)
          final done event adds: planId, planMessageId, planMarkdown
```

#### `POST /api/chat/plan/approve/stream` — Approve plan and execute
```
Request:  { planId, conversationId?, planMarkdown?, agentId? }
Response: SSE stream
```

#### `POST /api/chat/plan` — Create plan (sync, no stream)
```
Request:  { message, conversationId?, agentId?, cancelPlanId? }
Response: { conversationId, planId, planMessageId, planMarkdown, agentId? }
```

#### `POST /api/chat/message` — Send message (sync)
```
Request:  { message, conversationId? }
Response: { message: string, conversationId: string }
```

#### `GET /api/chat/messages?conversationId=X`
```
Response:
  messages:          { role, content, createdAt, messageId?, skillsCount?, kind?, planId? }[]
  conversationId:    string
  agentId?:          string
  lastStageOutputs?: Record<string, string>
  lastOutputFile?:   string
```

#### `GET /api/chat/conversations`
```
Response:
  conversations: [
    { id, agentId, title, messageCount, createdAt, updatedAt }
  ]
```

#### `DELETE /api/chat/conversations/{id}`
```
Response: 204 No Content
```

### Skills & Token Usage

#### `GET /api/chat/skills`
```
Response: [
  { id, name, emoji, description, stages: string[], stageLabels: Record<string, string> }
]
```

#### `GET /api/chat/skill-calls?messageId=X`
```
Response:
  skillCalls: [
    {
      id, skillId, runId,
      state: "running" | "done" | "error",
      input:  Record<string, unknown>,
      output: { type, event?, payload?, text?, data?, at? }[],
      error?: string,
      startedAt, endedAt?, durationMs?
    }
  ]
```

#### `GET /api/chat/token-usage?messageId=X`
```
Response:
  entries: [{ stage, provider, model, inputTokens, outputTokens }]
  totalInputTokens:  number
  totalOutputTokens: number
```

### Agents CRUD

#### `GET /api/agents`
```
Response: { agents: UiAgent[] }
```

#### `GET /api/agents/{id}`
```
Response: { agent: UiAgent }
```

#### `POST /api/agents`
```
Request:
  id, name, emoji, description: string
  allowedSkillIds:               string[]
  skillSelectorContext?:         string
  finalOutputFormattingContext?: string

Response: { agent: UiAgent }
```

#### `PATCH /api/agents/{id}`
```
Request:  Partial UiAgent (any fields)
Response: { agent: UiAgent }
```

#### `DELETE /api/agents/{id}`
```
Response: 204 No Content
```

---

## State — Where Data Lives

| Data | Location | Scope | Persisted to |
|------|----------|-------|-------------|
| Session (stage, Q1-Q3, RCA, recs) | RAM — `_sessions` dict (max 1000, LRU) | Per session | Async upsert → Supabase |
| Dynamic questions & answers | RAM → `session.questions_answers` | Per session | Supabase |
| Early recommendations | RAM → `session.early_recommendations` | Per session | Supabase |
| Final recs (extensions, gpts, companies) | RAM → `session.recommended_*` | Per session | Supabase |
| RCA diagnostic context | RAM → `session.rca_diagnostic_context` | Per session | Supabase |
| RCA handoff doc | RAM → `session.rca_handoff` | Per session | Supabase |
| Crawl raw data | RAM → `session.crawl_raw` | Per session | Supabase |
| Crawl summary | RAM → `session.crawl_summary` | Per session | Supabase |
| Business profile (scale Qs) | RAM → `session.business_profile` | Per session | Supabase |
| LLM call log | RAM → `session.llm_call_log` | Per session | Supabase |
| Playbook pipeline state | RAM → `session.playbook_*` | Per session | Supabase |
| Leads (CRM records) | Supabase `leads` table | Permanent | Supabase only |
| Phase 2 conversations & messages | SQLite `tools.db` | Permanent | SQLite only |
| Phase 2 skill call logs | SQLite `tools.db` | Permanent | SQLite only |
| RAG vector embeddings | Qdrant vector store | Permanent | Qdrant only |
| Sandbox test logs | RAM (sandbox_logger) | Dev only | Not persisted |
| JusPay orders | JusPay external system | Permanent | JusPay + Supabase via webhook |
| Auth (OTP verified, Google) | RAM session + Supabase | Per session | Supabase |

---

## Frontend File → API Calls Map

| File | API Calls Made |
|------|---------------|
| `ChatBotNew.tsx` | `/api/v1/agent/session`, `/session/outcome`, `/session/domain`, `/session/task`, `/session/answer`, `/session/website`, `/session/recommend`, `/api/v1/agent/session/{id}` (poll), `/api/v1/playbook/start`, `/playbook/gap-answers`, `/playbook/{id}` (poll), `/api/v1/auth/send-otp`, `/auth/verify-otp`, `/auth/google`, `/api/v1/payments/create-order`, `/api/search-companies`, `/api/chat` |
| `ChatBotNewMobile.tsx` | Same as ChatBotNew.tsx (mobile variant) |
| `phase2/api/client.ts` | `/api/chat/stream`, `/api/chat/plan/stream`, `/api/chat/plan/approve/stream`, `/api/chat/plan`, `/api/chat/message`, `/api/chat/messages`, `/api/chat/conversations`, `/api/chat/skill-calls`, `/api/chat/token-usage`, `/api/chat/skills`, `/api/agents` (full CRUD) |
| `SandboxPanel.tsx` | All `/api/v1/sandbox/*` endpoints |
| `SandboxLogin.tsx` | `/api/v1/sandbox/login` |

---

## Backend File Structure

```
backend/
├── app/
│   ├── main.py                      FastAPI app, lifespan, router registration, CORS
│   ├── config.py                    Pydantic Settings — reads all env vars
│   │
│   ├── routers/
│   │   ├── auth.py                  OTP + Google Sign-In
│   │   ├── chat.py                  Stage 1/2 chat (payment-gated at Stage 2)
│   │   ├── companies.py             Company list + AI-powered search
│   │   ├── speak.py                 OpenAI TTS → MP3
│   │   ├── leads.py                 Lead CRUD + conversation save
│   │   ├── payments.py              JusPay full lifecycle
│   │   ├── recommendations.py       Static extensions / GPTs / RCA data
│   │   ├── ideas.py                 Google Sheets webhook
│   │   ├── agent.py                 Main agent flow (session → recs)
│   │   ├── rag.py                   Qdrant ingest + semantic search
│   │   ├── sandbox.py               Dev testing panel with full logging
│   │   ├── playbook.py              5-agent playbook pipeline
│   │   └── legacy.py                Old route aliases (/api/chat, /api/companies, etc.)
│   │
│   ├── phase2/
│   │   ├── router.py                Research agent — streaming SSE, skill dispatch
│   │   ├── ai.py                    Claude API wrapper
│   │   ├── config.py                Phase 2 settings
│   │   ├── db.py                    SQLite schema (conversations, messages, skill_calls)
│   │   ├── skills.py                Skill registry (amazon-video, business-research, etc.)
│   │   ├── stores.py                DB read/write helpers
│   │   └── agent/
│   │       ├── orchestrator.py      Run agent turn (plan → skill → format)
│   │       ├── final_formatter.py   Format final markdown output
│   │       └── gemini_models.py     Gemini API calls
│   │
│   ├── models/
│   │   ├── session.py               SessionContext, SessionStage, all request/response models
│   │   ├── lead.py                  LeadCreate, LeadUpdate, LeadResponse
│   │   ├── payment.py               CreateOrderRequest, WebhookPayload, etc.
│   │   ├── company.py               Company, UserContext, SearchRequest
│   │   ├── chat.py                  ChatRequest, ChatResponse
│   │   └── speak.py                 SpeakRequest
│   │
│   ├── services/
│   │   ├── session_store.py         In-memory _sessions dict + LRU eviction
│   │   ├── user_session_service.py  Supabase auth + session persistence
│   │   ├── supabase_service.py      Leads CRUD, conversation save
│   │   ├── agent_service.py         Recommendation generation + audience analysis
│   │   ├── openai_service.py        GPT chat + TTS
│   │   ├── juspay_service.py        JusPay API calls
│   │   ├── otp_service.py           2Factor.in OTP
│   │   ├── persona_doc_service.py   Load persona markdown docs
│   │   ├── rca_tree_service.py      Pre-generated RCA decision tree
│   │   ├── instant_tool_service.py  Q1+Q2+Q3 instant tool matcher
│   │   ├── claude_rca_service.py    Claude adaptive RCA via OpenRouter
│   │   ├── playbook_service.py      5-agent playbook (Agents A, C, E) + OpenAI fallback
│   │   ├── sheets_service.py        Google Sheets company data
│   │   ├── crawl_service.py         Playwright website crawler
│   │   └── sandbox_logger.py        Dev panel event logger
│   │
│   ├── rag/
│   │   ├── ingest.py                Load tools JSON → OpenAI embeddings → Qdrant
│   │   ├── retrieval.py             Semantic search (query → embedding → Qdrant)
│   │   ├── vector_store.py          Qdrant client wrapper
│   │   └── models.py                ToolSearchRequest/Response
│   │
│   ├── middleware/
│   │   ├── rate_limit.py            Slowapi rate limiter
│   │   └── security.py              JusPay HMAC-SHA256 webhook verification
│   │
│   └── data/
│       ├── personas.py              Persona domain definitions
│       ├── categories.py            RCA category data
│       ├── chrome_extensions.py     Extension data
│       ├── custom_gpts.py           GPT data
│       └── rca_tree.py              Pre-gen RCA decision tree
│
├── .env                             All secrets (see .env.example for keys)
└── venv/                            Python virtualenv
```

---

## LLM Usage Summary

| Service | Model | Provider | Used For |
|---------|-------|----------|---------|
| `claude_rca_service.py` | `anthropic/claude-sonnet-4-6` | OpenRouter | Adaptive RCA questions, task filtering |
| `playbook_service.py` | `z-ai/glm-5` (default) | OpenRouter | Agents A, C, E playbook generation |
| `playbook_service.py` | `anthropic/claude-sonnet-4-6` | OpenRouter | Playbook Agent C (comparison) |
| `playbook_service.py` | `gpt-4o-mini` | OpenAI direct | Fallback when OpenRouter returns 402 |
| `openai_service.py` | `gpt-4o-mini` | OpenAI | Stage 1/2 chat, TTS, audience analysis |
| `phase2/ai.py` | `claude-*` | Anthropic direct | Research agent turns |

---

*Last updated: March 2026 — covers life-sorter-v9 copy, branch: datamigration*
