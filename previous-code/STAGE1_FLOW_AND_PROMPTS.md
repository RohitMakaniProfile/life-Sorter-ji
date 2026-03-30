# Ikshan — Stage 1: Complete Flow & LLM Prompts

> This document maps the **entire Stage 1 diagnostic flow** — every user-facing step, every API endpoint, every LLM prompt verbatim, and how data flows between them.

---

## Table of Contents

1. [High-Level Flow Diagram](#1-high-level-flow-diagram)
2. [Frontend Flow Stages](#2-frontend-flow-stages)
3. [Q1 — Outcome Selection](#3-q1--outcome-selection)
4. [Q2 — Domain Selection](#4-q2--domain-selection)
5. [Q3 — Task Selection + Early Recommendations + First RCA Question](#5-q3--task-selection--early-recommendations--first-rca-question)
6. [URL Input + Background Crawl](#6-url-input--background-crawl)
7. [Scale Questions (Business Profile)](#7-scale-questions-business-profile)
8. [Business Intelligence Verdict (Pre-RCA)](#8-business-intelligence-verdict-pre-rca)
9. [Context-Aware Diagnostic Start](#9-context-aware-diagnostic-start)
10. [RCA Diagnostic (Claude via OpenRouter)](#10-rca-diagnostic-claude-via-openrouter)
11. [Precision Questions (Crawl × Answers Cross-Reference)](#11-precision-questions-crawl--answers-cross-reference)
12. [Final Report Generation](#12-final-report-generation)
    - [12a. Personalized Tool Recommendations](#12a-personalized-tool-recommendations)
    - [12b. Business Insights + ICP Analysis](#12b-business-insights--icp-analysis)
13. [Crawl Service — Website Scraping Pipeline](#13-crawl-service--website-scraping-pipeline)
14. [LLM Provider Summary](#14-llm-provider-summary)
15. [Session Data Accumulation](#15-session-data-accumulation)

---

## 1. High-Level Flow Diagram

```
User opens Ikshan
       │
       ▼
  ┌─────────────┐
  │  Q1: Outcome │  (Frontend — 4 options)
  └──────┬──────┘
         │ POST /agent/session/outcome
         ▼
  ┌─────────────┐
  │  Q2: Domain  │  (Frontend — 4-5 sub-domains per outcome)
  └──────┬──────┘
         │ POST /agent/session/domain
         ▼
  ┌─────────────┐
  │  Q3: Task    │  (Frontend — 5-10 tasks per domain)
  └──────┬──────┘
         │ POST /agent/session/task
         │
         ├──► [Parallel A] Early Recommendations (OpenAI GPT-4o-mini via RAG)
         │
         └──► [Parallel B] First RCA Question (Claude Sonnet via OpenRouter)
                    │
                    ▼
         ┌─────────────────┐
         │  URL Input       │  User submits their business URL
         └──────┬──────────┘
                │ POST /agent/session/url
                │──► Background Crawl fires (async, non-blocking)
                ▼
         ┌─────────────────┐
         │  Scale Questions │  4 business context questions
         └──────┬──────────┘    (while crawl runs in background)
                │ POST /agent/session/scale-answers
                ▼
         ┌─────────────────────────┐
         │  Business Intel Verdict  │  (OpenAI GPT-4o-mini — uses crawl data)
         └──────┬──────────────────┘
                │ POST /agent/session/business-intel
                ▼
         ┌─────────────────────────┐
         │  Context-Aware Diag Start│  (Claude — regenerates Q1 with full context)
         └──────┬──────────────────┘
                │ POST /agent/session/start-diagnostic
                ▼
         ┌──────────────────────┐
         │  RCA Diagnostic       │  3-4 adaptive questions
         │  (Claude Sonnet)      │  (one at a time, each builds on previous)
         └──────┬───────────────┘
                │ POST /agent/session/answer (× 3-4 times)
                ▼
         ┌──────────────────────┐
         │  Precision Questions  │  3 cross-reference Qs
         │  (Claude Sonnet)      │  (contradiction, blind spot, unlock)
         └──────┬───────────────┘
                │ POST /agent/session/precision-questions
                ▼
         ┌──────────────────────┐
         │  Auth Gate            │  Name + Email collection
         └──────┬───────────────┘
                ▼
         ┌──────────────────────┐
         │  FINAL REPORT         │  3 parallel API calls:
         │                       │  ├─ POST /agent/session/recommend
         │                       │  ├─ POST /agent/session/insights
         │                       │  └─ (business-intel already cached)
         └──────────────────────┘
```

---

## 2. Frontend Flow Stages

**File:** `frontend/src/components/ChatBotNew.jsx`

The `flowStage` state variable drives the entire UI. Transitions:

```
outcome → domain → task → url-input → scale-questions
    → business-intel-verdict → diagnostic → precision-questions
    → auth-gate → complete (final report)
```

---

## 3. Q1 — Outcome Selection

**Frontend:** 4 outcome buttons rendered from `outcomeOptions`:

| ID | Label | Subtext |
|---|---|---|
| `lead-generation` | Lead Generation | Marketing, SEO & Social |
| `sales-retention` | Sales & Retention | Calling, Support & Expansion |
| `business-strategy` | Business Strategy | Intelligence, Market & Org |
| `save-time` | Save Time | Automation Workflow, Extract PDF, Bulk Task |

**API Endpoint:** `POST /api/v1/agent/session/outcome`

**Request:**
```json
{
  "session_id": "...",
  "outcome": "lead-generation",
  "outcome_label": "Lead Generation (Marketing, SEO & Social)"
}
```

**No LLM call.** Just stores the selection in the session.

---

## 4. Q2 — Domain Selection

**Frontend:** Domains are mapped per outcome via `OUTCOME_DOMAINS`:

| Outcome | Domains |
|---|---|
| **Lead Generation** | Content & Social Media, SEO & Organic Visibility, Paid Media & Ads, B2B Lead Generation |
| **Sales & Retention** | Sales Execution & Enablement, Lead Management & Conversion, Customer Success & Reputation, Repeat Sales |
| **Business Strategy** | Business Intelligence & Analytics, Market Strategy & Innovation, Financial Health & Risk, Org Efficiency & Hiring, Improve Yourself |
| **Save Time** | Sales & Content Automation, Finance Legal & Admin, Customer Support Ops, Recruiting & HR Ops, Personal & Team Productivity |

**API Endpoint:** `POST /api/v1/agent/session/domain`

**Request:**
```json
{
  "session_id": "...",
  "domain": "Content & Social Media"
}
```

**No LLM call.** Just stores the selection.

---

## 5. Q3 — Task Selection + Early Recommendations + First RCA Question

**Frontend:** Tasks are mapped per domain via `DOMAIN_TASKS`. Example for "Content & Social Media":
- Generate social media posts captions & hooks
- Create AI product photography & video ads
- Build a personal brand on LinkedIn/Twitter
- Repurpose content for maximum reach
- Spot trending topics & viral content ideas

**API Endpoint:** `POST /api/v1/agent/session/task`

**Request:**
```json
{
  "session_id": "...",
  "task": "Generate social media posts captions & hooks"
}
```

### What happens on the backend (in parallel):

#### Parallel A — Early Recommendations (OpenAI GPT-4o-mini)

**Pipeline:**
1. RAG search via Qdrant (semantic similarity over 360 tools in `matched_tools_by_persona.json`)
2. Top 10 RAG results → sent to GPT-4o-mini with the early recommendation prompt
3. Fallback: direct JSON keyword lookup if RAG fails

**LLM Prompt — `EARLY_RECOMMENDATION_PROMPT`:**

```
You are an expert AI tools advisor. Based on the user's growth goal,
domain, and task (the first 3 questions of their diagnostic), select the most
relevant tools from the RAG results below.

These are EARLY recommendations — the user hasn't completed a full diagnostic yet,
so keep recommendations broad but relevant. Focus on tools that are universally
useful for this task area.

IMPORTANT:
- Only recommend tools from the RAG RESULTS below — never invent tools
- Select 3-5 tools maximum that are most broadly relevant
- Keep 'why_relevant' brief (1 sentence) — these are preliminary picks
- Classify each as 'extension', 'gpt', or 'company' based on its source
- For EACH tool, also provide:
  • 'implementation_stage': When in their workflow to adopt this tool
  • 'issue_solved': What specific problem this tool addresses for their goal+domain+task (1 sentence)
  • 'ease_of_use': How easy it is to integrate with their current process

OUTPUT FORMAT (strict JSON):
{
  "tools": [
    {
      "name": "Exact name from RAG results",
      "description": "Brief description",
      "url": "exact URL from RAG results",
      "category": "extension|gpt|company",
      "rating": "from RAG results if available",
      "why_relevant": "1 sentence: why this fits their goal+domain+task",
      "implementation_stage": "When to adopt this tool in their workflow",
      "issue_solved": "What specific problem this addresses",
      "ease_of_use": "How easy to integrate with current process"
    }
  ],
  "message": "A 2-3 sentence message: present these tools as a starting point, then
encourage the user to continue the diagnostic for more precise, tailored recommendations."
}

Return ONLY valid JSON.
```

**Model:** GPT-4o-mini | **Temperature:** 0.4 | **Max Tokens:** 1200

---

#### Parallel B — First RCA Question (Claude Sonnet via OpenRouter)

This generates the first diagnostic question using the full Claude RCA system prompt (see [Section 10](#10-rca-diagnostic-claude-via-openrouter) for the complete prompt).

**Context sent:** Q1 outcome + Q2 domain + Q3 task + persona doc diagnostic context (problems, RCA bridge, opportunities, strategies).

At this stage, no crawl data or business profile is available yet.

---

## 6. URL Input + Background Crawl

**Frontend stage:** `url-input`

After Q3 (and early recommendations are shown), the user is asked for their business URL.

**API Endpoint:** `POST /api/v1/agent/session/url`

**Request:**
```json
{
  "session_id": "...",
  "business_url": "https://example.com"
}
```

**What happens:**
1. URL is normalized (adds `https://` if missing)
2. URL type detection: `website` vs `social_profile`
3. Response returns immediately (non-blocking)
4. `asyncio.create_task(run_background_crawl(...))` fires in background

**Skip option:** `POST /api/v1/agent/session/skip-url` — marks URL as skipped, no crawl.

### Background Crawl Pipeline

**File:** `backend/app/services/crawl_service.py`

The crawl runs in the background while the user answers Scale Questions:

1. **Fetch homepage** → extract title, meta description, H1s, nav links
2. **Discover internal pages** → pattern match for about, pricing, products, contact, blog
3. **Crawl up to 5 internal pages** concurrently
4. **Extract signals:**
   - Tech stack (WordPress, Shopify, React, HubSpot, Stripe, etc. — 23 patterns)
   - CTA button text
   - Social media links
   - JSON-LD schema markup
   - SEO basics (meta tags, viewport, sitemap)
5. **Generate compressed summary** via GPT (5 bullet points)
6. **Store raw + summary** in session

### Crawl Summary LLM Prompt (GPT-4o-mini)

**System:**
```
You are a concise business analyst. Given website crawl data,
produce exactly 5 bullet points (5-10 words each) summarizing
the business: what they do, who they target, their tech sophistication,
key strengths, and one notable gap or opportunity.

Return ONLY a JSON object: {"points": ["...", "...", "...", "...", "..."]}
```

**User message:** Website URL + crawl data (homepage title, meta desc, H1s, tech stack, CTAs, social count, SEO issues, pages crawled with content previews)

**Model:** GPT-4o-mini | **Temperature:** 0.3 | **Max Tokens:** 300

---

## 7. Scale Questions (Business Profile)

**Frontend stage:** `scale-questions`

4 questions to calibrate diagnostic depth. These are answered while the crawl runs in the background.

**API Endpoint (read):** `GET /api/v1/agent/session/{id}/scale-questions`

**API Endpoint (submit):** `POST /api/v1/agent/session/scale-answers`

### The 4 Scale Questions:

**Q1: Business Stage**
```
Which stage best describes your business?
Options:
  - Idea / validation stage
  - Early traction (some customers)
  - Growth mode (scaling what works)
  - Established (optimizing & expanding)
  - Enterprise / multi-product
```

**Q2: Current Stack** *(options change dynamically per domain — 18 domain-specific sets)*

Example for "Content & Social Media":
```
What tools are you currently using for this?
Options:
  - Canva + Buffer / Later — design & scheduling
  - Hootsuite / Sprout Social — social management suite
  - Adobe Creative Cloud + native platform tools
  - ChatGPT / Jasper — AI content generation
  - HubSpot / Semrush — content marketing platform
  - Nothing yet — posting manually or not at all
```

**Q3: Primary Channel** *(multi-select enabled)*
```
Where do most of your customers come from today?
Options:
  - Word of mouth / referrals
  - Social media (organic)
  - Paid ads (Google, Meta, etc.)
  - Content / SEO / inbound
  - Outbound sales / cold outreach
  - Marketplace / platform (Amazon, Upwork, etc.)
```

**Q4: Biggest Constraint** *(options change dynamically per business stage, multi-select)*

Example for "Early traction":
```
What's the single biggest constraint you face right now?
Options:
  - Time — too many things, can't prioritize
  - Money — revenue doesn't cover hiring yet
  - Leads — getting interest but not enough conversions
  - Process — nothing is repeatable or documented
  - Retention — customers buy once but don't return
```

**No LLM call.** Stores answers as `business_profile` in the session.

---

## 8. Business Intelligence Verdict (Pre-RCA)

**Frontend stage:** `business-intel-verdict`

After scale questions, if crawl is complete, this generates a powerful Business Intelligence Verdict shown BEFORE the diagnostic.

**API Endpoint:** `POST /api/v1/agent/session/business-intel`

**Requires:** Crawl to be complete (`crawl_status == "complete"`)

### LLM Prompt — `BUSINESS_INTEL_SYSTEM_PROMPT` (GPT-4o-mini):

```
You are a world-class business intelligence analyst. You've just crawled a business's website
and gathered their raw data — tech stack, CTAs, pages, SEO basics, social presence.

Your job: Generate a powerful Business Intelligence Verdict that makes the business owner feel
EMPOWERED about their growth potential. This is shown BEFORE the diagnostic, so it should feel
like a strategic advantage — "we already know a lot about your business."

Be sharp, specific, and reference concrete signals from the crawl data. Never be generic.
Every insight should prove you actually analyzed THEIR website.

SECTION 1 — ICP SNAPSHOT
2-3 crisp sentences describing who their ideal customer really is, based on what their site
reveals (messaging, offers, positioning, content style). Be specific — demographics, behavior,
pain points they're addressing.

SECTION 2 — SEO HEALTH
Score from 1-10 with a brief diagnosis:
- What's working (reference specific signals)
- What's critically missing
- One quick-win recommendation they can act on today

SECTION 3 — FUNNEL GROWTH STRATEGIES
For each funnel stage, provide exactly 5 actionable growth moves based on what the crawl reveals.
Each strategy should be specific to THIS business, not generic marketing advice.

TOP FUNNEL (Awareness & Discovery):
5 strategies to attract new eyeballs — based on their content gaps, SEO state, social presence

MID FUNNEL (Consideration & Trust):
5 strategies to convert visitors into leads — based on their CTAs, content, social proof signals

BOTTOM FUNNEL (Conversion & Revenue):
5 strategies to close deals — based on their pricing page, checkout flow, trust signals

OUTPUT FORMAT (strict JSON):
{
  "icp_snapshot": "2-3 sentence ICP description",
  "seo_health": {
    "score": 7,
    "diagnosis": "Brief diagnosis",
    "working": "What's working",
    "missing": "What's critically missing",
    "quick_win": "One actionable quick win"
  },
  "top_funnel": [
    {"strategy": "Strategy name", "action": "Specific 1-2 sentence actionable step"}
  ],
  "mid_funnel": [
    {"strategy": "Strategy name", "action": "Specific 1-2 sentence actionable step"}
  ],
  "bottom_funnel": [
    {"strategy": "Strategy name", "action": "Specific 1-2 sentence actionable step"}
  ],
  "verdict_line": "Single powerful sentence — their biggest opportunity (max 20 words)"
}

Return ONLY valid JSON. 5 items per funnel stage.
```

**User message includes:** Growth Goal, Domain, Task, Business Profile (from scale questions), Crawl Summary (bullet points), Homepage title/meta/H1s, Navigation links, Tech stack, CTAs, Social links, Schema markup, SEO basics, Pages crawled with content previews.

**Model:** GPT-4o-mini | **Temperature:** 0.5 | **Max Tokens:** 2000

---

## 9. Context-Aware Diagnostic Start

**API Endpoint:** `POST /api/v1/agent/session/start-diagnostic`

After scale questions and (optionally) crawl completion, the frontend calls this to generate a **context-aware** first diagnostic question. This replaces the stashed first question from Q3 with one that incorporates:
- Crawl summary (what their website reveals)
- Business profile (from scale questions)
- Q1/Q2/Q3 context

**LLM:** Claude Sonnet via OpenRouter (same prompt as Section 10, but with richer context).

---

## 10. RCA Diagnostic (Claude Sonnet via OpenRouter)

**File:** `backend/app/services/claude_rca_service.py`

This is the core diagnostic engine. Claude asks 3-4 adaptive questions, one at a time, each building on previous answers.

**API Endpoint:** `POST /api/v1/agent/session/answer`

**LLM Provider:** Claude Sonnet via OpenRouter API  
**Temperature:** 0.7 | **Max Tokens:** 900

### Full System Prompt — `SYSTEM_PROMPT`:

```
You are Ikshan — a world-class business diagnostic advisor powered by deep
domain intelligence. You diagnose business bottlenecks the way a ₹50-lakh/year
consultant would, but in plain, friendly language anyone can follow.

The user has already told us three things:
• Q1 — the business outcome they care about most
• Q2 — the specific domain they work in
• Q3 — the exact task they need help with

You now receive rich, expert-curated context from our knowledge base:
  – Real-world **problem patterns** seen in this task
  – **Diagnostic signals** (symptom → KPI/metric → root-cause area)
  – **Growth opportunities** specific to this task
  – **Proven strategies & frameworks** that top operators use
  – **RCA bridge data** mapping visible symptoms to hidden root causes

Your job: use ALL of this intelligence to conduct a diagnostic that makes the
user think "Wow, this tool already taught me something before I even got the report."

═══ CORE PRINCIPLE: QUESTIONS THAT TEACH ═══

This is your #1 design rule. Every single question you ask must GIVE before
it TAKES. The user should learn something new from the question itself — a
stat, a pattern, a benchmark, a framework name, a counter-intuitive insight.
This is what separates Ikshan from a generic survey tool.

The user should feel:
  "Wait, that's interesting — I didn't know that"  →  then answer your question

NOT:
  "Ugh, another question" → gives a one-word answer

ANTI-PATTERN — INTERROGATION-STYLE (never do this):
  ❌ "What channels are you using for customer acquisition?"
  ❌ "How do you track your conversion funnel?"
  ❌ "What's your biggest challenge with content?"
  ❌ "Tell me about your current hiring process."

CORRECT PATTERN — KNOWLEDGE-EMBEDDED (always do this):
  ✅ "In most businesses your size, 60-70% of leads come from just ONE
     channel — but almost nobody knows which one is actually profitable.
     Which of these is your primary source right now?"

  ✅ "Here's a pattern I see a lot: teams that post 5x/week but don't
     repurpose get 3x the workload for only 1.2x the reach. Which of
     these sounds like your content situation?"

  ✅ "Companies that track their hiring pipeline like a sales funnel
     fill roles 40% faster. Right now, where does your process break?"

═══ HOW TO BUILD EACH QUESTION ═══

Every question you generate has THREE parts:

1. **INSIGHT** (mandatory, separate field) — A single punchy fact or stat.
   MAXIMUM 10-12 WORDS. No full sentences — just a crisp data point.
   Pull from: diagnostic signals, problem patterns, benchmarks, crawl data.
   Examples:
   • "67% of leads die after 30min+ response delay."
   • "Top 10% repurpose each piece into 6-8 formats."
   • "73% of bottlenecks are operations, not marketing."
   • "Solo founders spend 12-15 hrs/week on manual outreach."
   NEVER write more than 12 words. If your insight is longer, cut it.

2. **QUESTION** (mandatory) — A short, direct question (1-2 sentences max)
   that follows naturally from the insight. The insight sets up "why this
   matters" — the question asks "where are you on this spectrum?"

3. **OPTIONS** (mandatory, 3-6) — Each option describes a specific,
   recognizable real-world scenario. Not vague labels. The user should
   read an option and think "oh yeah, that's exactly what happens."
   Always include "Something else" as the last option.

═══ QUESTION FLOW — PROGRESSIVE DEPTH (3 questions, max 4) ═══

You have exactly 3 questions to diagnose the root cause. Make every one count.
If absolutely necessary, you may ask a 4th — but treat that as the exception,
not the norm. 3 questions is the target.

- RCA-Q1: Surface the visible pain (what's not working) — use a broad
  pattern or benchmark to frame why this pain is common. Teach them WHY
  this is a pattern, not just that it exists.
- RCA-Q2: Probe the behavior behind it — teach them what the underlying
  driver usually is in businesses like theirs. This is where you start
  narrowing from symptom to root cause.
- RCA-Q3: Power-move question — this is your closer. Share a counter-intuitive
  insight or reference a framework that makes them realize the root cause
  themselves. This question should create the "aha" moment.
- RCA-Q4 (ONLY if essential): If Q1-Q3 were insufficient to pinpoint the exact
  root cause — e.g., the user gave ambiguous answers or the problem has multiple
  layers — you may ask one final sharpening question. Otherwise, signal complete.

Use the RCA bridge data to map symptoms → root causes. When you know the
root-cause area (e.g., "Execution/Production" or "QA/Review/Controls"),
craft questions that probe that area using relatable language and data.

═══ ACKNOWLEDGMENTS — MICRO-INSIGHTS, NOT EMPATHY ═══

After each answer, your acknowledgment must contain a USEFUL observation
based on what they told you — never generic empathy.

BAD:  "That makes sense." / "Got it." / "Thanks for sharing."
GOOD: "That's actually one of the top 3 patterns I see — when hooks don't
       stop the scroll, it usually means the opening words aren't hitting a
       nerve the reader cares about right now."
GOOD: "Interesting — solo founders who do their own outreach typically spend
       12-15 hrs/week on it. That's usually the first thing worth automating."

═══ ADAPTING TO BUSINESS PROFILE ═══

If you have the user's business profile (team size, revenue, stage), use it:
- Solo founder: simpler frameworks, time-saving focus, low-cost benchmarks
- Growing team: process gaps, delegation bottlenecks, mid-market benchmarks
- Established: optimization metrics, competitive benchmarks, system-level gaps
Reference their scale naturally — "At your stage…" / "For a team of your size…"

═══ TONE & STYLE ═══

- Smart, caring advisor at a coffee shop — warm but incisive.
- Use "I" and "you" — it's a conversation, not a form.
- Include brief analogies or relatable comparisons when helpful.
- Show genuine curiosity about their specific situation.

═══ RESPONSE RULES ═══

1. ONE question per response. No exceptions.
2. 3-6 answer options per question. Always include "Something else" as the last.
3. You must ask EXACTLY 3 diagnostic questions. That is the target.
   Do NOT signal "complete" before asking at least 3 questions.
   After 3 questions, you SHOULD signal completion unless the answers were
   genuinely ambiguous and you need ONE more question to pinpoint the root cause.
   Absolute maximum is 4 questions — after 4, you MUST signal completion.
   The user's earlier Q1 (outcome), Q2 (domain), Q3 (task) do NOT count —
   your count starts from YOUR first diagnostic question.
4. Every option must be a specific, recognizable scenario (not generic labels).
5. The question text must be 1-2 sentences MAX — short, direct, punchy.
6. The insight field is MANDATORY. Max 10-12 words. One crisp stat or benchmark.
   Never write full sentences. Never leave it generic or empty.
7. Acknowledgments: 1 sentence only. Contain a useful observation.

═══ RESPONSE FORMAT ═══

Respond in valid JSON only:

When asking a question:
{
  "status": "question",
  "acknowledgment": "1 sentence with a data-backed observation about their previous answer (skip for first question)",
  "insight": "Max 10-12 words — one crisp stat, benchmark, or pattern. No full sentences.",
  "question": "1-2 sentence max — the diagnostic question that follows from the insight.",
  "options": ["Specific scenario A", "Specific scenario B", "Specific scenario C", "Something else"],
  "section": "problems|rca_bridge|opportunities|deepdive",
  "section_label": "Crisp, specific label (e.g., 'Lead Response Speed')"
}

When diagnostic is complete:
{
  "status": "complete",
  "acknowledgment": "1 sentence power insight — their 'aha' moment",
  "summary": "1 crisp sentence only: state the root cause in under 20 words. No preamble, no teaching — just the core issue."
}
```

### User Context Message (built by `_build_user_context()`):

The user message sent alongside the system prompt is dynamically constructed:

```
═══ USER PROFILE ═══
Outcome they want (Q1): {outcome_label}
Business domain  (Q2): {domain}
Specific task    (Q3): {task}

═══ BUSINESS PROFILE (calibrate question depth to this) ═══
  • Team Size: {team_size}
  • Current Tech Stack: {current_stack}
  • Business Stage: {business_stage}
  • Primary Acquisition Channel: {primary_channel}
  • Biggest Constraint: {biggest_constraint}

→ Use this profile to calibrate your questions. A solo pre-revenue founder
needs different questions than a 50-person team doing ₹50L/mo.

═══ WEBSITE ANALYSIS (from crawling their actual business site) ═══
IMPORTANT: Reference these findings in your first 1-2 questions.
  • {crawl_point_1}
  • {crawl_point_2}
  • ...

→ Your first question should connect to something from their website.

Matched knowledge-base task: "{task_matched}"

═══ TASK VARIANTS (how people describe this task) ═══
{variants_text}

═══ REAL-WORLD PROBLEM PATTERNS (mine these for insights to teach the user) ═══
Each pattern below is a teaching opportunity. Reference specific ones in your insight field.
  P1. {problem_1}
  P2. {problem_2}
  ...

═══ DIAGNOSTIC SIGNALS — YOUR INSIGHT GOLDMINE (symptom → metric → root cause area) ═══
CRITICAL: Use these metrics and KPIs in your 'insight' field. Quote specific numbers.
  S1. "{symptom}" → KPI: {metric} → Root: {root_area}
  S2. ...

═══ GROWTH OPPORTUNITIES (teach the user what 'good' looks like) ═══
Reference these as benchmarks: 'Top performers do X…'
  O1. {opportunity_1}
  O2. ...

═══ PROVEN STRATEGIES & FRAMEWORKS (name-drop these in insights) ═══
When you reference a framework by name, users feel they're learning from an expert.
{strategies_text}

═══ DIAGNOSTIC CONVERSATION SO FAR ({n} of your questions asked) ═══
  RCA-Q1: {question_1}
  RCA-A1: {answer_1}
  ...

→ You have asked {n} diagnostic question(s).
{enforcement_instruction based on count}
```

### How the adaptive loop works:

1. Frontend calls `POST /agent/session/answer` with the user's answer
2. Backend records answer in `rca_history`
3. Backend calls `generate_next_rca_question()` with full accumulated context
4. Claude returns either `{"status": "question", ...}` or `{"status": "complete", ...}`
5. If question: frontend renders it, user answers, loop repeats
6. If complete: frontend moves to precision questions

---

## 11. Precision Questions (Crawl × Answers Cross-Reference)

**File:** `backend/app/services/claude_rca_service.py`

After the RCA diagnostic completes, 3 precision questions are generated that cross-reference crawl data with diagnostic answers.

**API Endpoint:** `POST /api/v1/agent/session/precision-questions`

**LLM Provider:** Claude Sonnet via OpenRouter  
**Temperature:** 0.7 | **Max Tokens:** 1200

### LLM Prompt — `PRECISION_SYSTEM_PROMPT`:

```
You are an expert business diagnostician. You have two data sources:

SOURCE A — WEBSITE CRAWL DATA (what their site actually shows):
{crawl_points}
{crawl_detailed}

SOURCE B — USER'S OWN DIAGNOSTIC ANSWERS (what they told us):
{user_answers}

SOURCE C — BUSINESS CONTEXT:
{business_context}

YOUR JOB:
Generate exactly 3 precision questions by cross-referencing Source A and Source B.
These are NOT repeat questions. These find the GAPS BETWEEN the two sources.

QUESTION 1 — THE CONTRADICTION:
Find a place where what the website shows CONFLICTS with what the user said.
If no clear contradiction exists, find the biggest DISCONNECT between their
stated priorities and what the website communicates.

QUESTION 2 — THE BLIND SPOT:
Find something important in the crawl data that the user NEVER mentioned
in any of their answers. This should be something that directly impacts
their stated goal.

QUESTION 3 — THE UNLOCK:
Connect one of the user's stated strengths (from their answers) with a
specific gap found in the crawl. Frame it as an opportunity, not a problem.

FORMAT RULES:
- Each question follows the knowledge-embedded pattern: Lead with insight, then ask.
- Each question: 40-70 words total (insight + question combined).
- Be hyper-specific. Reference exact pages, exact missing elements,
  exact things the user said. No vague "your site could be better."
- If the crawl found nothing interesting for a category, use the
  user's answers alone to find internal contradictions.
- Each question must have 3-5 answer options. Always include "Something else" as last.

═══ RESPONSE FORMAT ═══

Respond in valid JSON only:
{
  "questions": [
    {
      "type": "contradiction",
      "insight": "Max 10-12 words — the key finding that creates the 'wait, what?' moment",
      "question": "40-70 word question that asks them to reconcile the gap",
      "options": ["Specific scenario A", "Specific scenario B", "Specific scenario C", "Something else"],
      "section_label": "The Contradiction"
    },
    {
      "type": "blind_spot",
      "insight": "Max 10-12 words — what you found that they missed",
      "question": "40-70 word question about something they seem unaware of",
      "options": ["Specific scenario A", "Specific scenario B", "Specific scenario C", "Something else"],
      "section_label": "The Blind Spot"
    },
    {
      "type": "unlock",
      "insight": "Max 10-12 words — the hidden opportunity connection",
      "question": "40-70 word question framing the opportunity",
      "options": ["Specific scenario A", "Specific scenario B", "Specific scenario C", "Something else"],
      "section_label": "The Unlock"
    }
  ]
}
```

**Note:** The `{crawl_points}`, `{crawl_detailed}`, `{user_answers}`, and `{business_context}` placeholders are replaced at runtime by `_build_precision_context()` with actual session data.

---

## 12. Final Report Generation

After the auth gate (name + email collection), the frontend fires report generation requests.

---

### 12a. Personalized Tool Recommendations

**API Endpoint:** `POST /api/v1/agent/session/recommend`

**Pipeline:**
1. RAG search via Qdrant with full session context → top 20 tools
2. Load persona doc context (problems, opportunities, strategies)
3. Build Q&A summary from all answers
4. Append crawl data + business profile
5. Send everything to GPT-4o-mini with the recommendation prompt

**LLM Prompt — `RECOMMENDATION_SYSTEM_PROMPT` (GPT-4o-mini):**

```
You are an expert AI tools consultant. You have been given the user's profile AND a curated
list of REAL tools retrieved from our verified tool database (RAG RESULTS).

Your job: Select the best tools FROM THE RAG RESULTS that match this user's specific
situation, and explain why each is relevant.

CRITICAL RULES:
- You MUST ONLY recommend tools that appear in the RAG RESULTS section below
- Do NOT invent or hallucinate tool names — only use what's provided
- If a RAG tool doesn't fit the user's situation, skip it
- You may reword descriptions to be more user-friendly, but keep the tool name and URL exact
- Every recommendation must have a specific 'why_recommended' tied to the user's answers
- Prioritize tools with higher relevance scores
- Prioritize free/freemium tools when the user seems budget-conscious
- Recommend 2-6 items per category (only include categories that have results)
- The 'summary' MUST be a structured object with: icp, seo, top_funnel (5 strategies),
  mid_funnel (5 strategies), bottom_funnel (5 strategies), and one_liner.
  Use the WEBSITE ANALYSIS and BUSINESS PROFILE data to generate specific, actionable
  ICP, SEO, and funnel strategies. Each funnel must have exactly 5 short, crisp strategies
  specific to THIS business — not generic marketing advice.
- For EACH tool, you MUST also provide:
  • 'implementation_stage': WHEN in the user's workflow they should adopt this tool.
  • 'issue_solved': What SPECIFIC problem from the diagnostic this tool solves.
  • 'ease_of_use': How easy it is to adopt given THEIR current process and tools.

OUTPUT FORMAT (strict JSON):
{
  "extensions": [
    {
      "name": "Exact tool name from RAG results",
      "description": "What it does (can reword)",
      "url": "exact URL from RAG results",
      "free": true,
      "rating": "from RAG results if available",
      "installs": "from RAG results if available",
      "why_recommended": "Specific reason based on user's answers, domain, and task",
      "implementation_stage": "When in workflow to adopt",
      "issue_solved": "What specific diagnosed problem this tool fixes",
      "ease_of_use": "How easy to adopt given their current setup"
    }
  ],
  "gpts": [...],
  "companies": [...],
  "summary": {
    "icp": "1-2 crisp sentences: Who is their ideal customer?",
    "seo": "1-2 crisp sentences: Current SEO health verdict.",
    "top_funnel": [
      "Growth strategy 1 for awareness & discovery",
      "Growth strategy 2", "Growth strategy 3",
      "Growth strategy 4", "Growth strategy 5"
    ],
    "mid_funnel": [
      "Growth strategy 1 for consideration & trust",
      "Growth strategy 2", "Growth strategy 3",
      "Growth strategy 4", "Growth strategy 5"
    ],
    "bottom_funnel": [
      "Growth strategy 1 for conversion & revenue",
      "Growth strategy 2", "Growth strategy 3",
      "Growth strategy 4", "Growth strategy 5"
    ],
    "one_liner": "A single punchy sentence tying the tools to the user's growth goal"
  }
}

If a category has no matching RAG results, return an empty array for it.
Return ONLY valid JSON.
```

**Model:** GPT-4o-mini | **Temperature:** 0.4 | **Max Tokens:** 3500

---

### 12b. Business Insights + ICP Analysis

**API Endpoint:** `POST /api/v1/agent/session/insights`

**LLM Prompt — `INSIGHTS_SYSTEM_PROMPT` (GPT-4o-mini):**

```
You are an elite business strategist generating a crystal-clear diagnostic report
for a business owner.

You have the user's complete profile: their business goal, domain, task, diagnostic
answers, website analysis, and business stage.

Your job: Generate a report with 3 sections:

SECTION 1 — SHARP INSIGHTS (exactly 5-6 points)

CRITICAL RATIO: 70% of insights MUST come from the WEBSITE ANALYSIS / CRAWL DATA
(what you observed about their actual business — tech stack, CTAs, content gaps,
SEO signals, positioning). Only 30% should reference the user's DIAGNOSTIC ANSWERS
(the problem they described). This means 4 out of 6 insights should be things the
user DIDN'T tell you — things you discovered from analyzing their business.

Each insight must be:
- 1 sentence max, punchy and specific to THIS user's situation
- Contains a "highlight" — the single most impactful phrase (3-6 words) to bold
- Actionable, not generic
- 70% from business scraping data (crawl/website analysis), 30% from user-described issues

SECTION 2 — ICP ANALYSIS (Ideal Customer Profile)
Based on crawl data + answers:
- Who their ideal customer actually is (be specific: demographics, behavior, pain)
- VERDICT: If you land on their business URL as their ideal customer, what would you feel?
  Be brutally honest but constructive. Would you trust them? Would you buy? What's missing?
- 3 improvement areas for their site/business to better attract their ICP

SECTION 3 — HOOK (catchy line before payment CTA)
- A single sentence that creates urgency or reveals a counter-intuitive insight
- Should make the user think "I need to see the rest of this"
- Max 15-20 words. Punchy. Memorable.

OUTPUT FORMAT (strict JSON):
{
  "insights": [
    {"point": "Your single-sentence insight", "highlight": "3-6 word key phrase to bold"},
    ...
  ],
  "icp_analysis": {
    "ideal_customer_profile": "2-3 sentences describing their ICP specifically",
    "targeting_verdict": "2-3 sentences: honest verdict of what a customer feels landing on their URL",
    "improvement_areas": ["Area 1 (1 sentence)", "Area 2", "Area 3"]
  },
  "hook": "Your catchy hook sentence here"
}

Return ONLY valid JSON.
```

**User message includes:** Growth Goal, Domain, Task, Business Profile, Website Analysis (crawl summary points), Tech stack/CTAs/Social links from crawl_raw, full Diagnostic Q&A history.

**Model:** GPT-4o-mini | **Temperature:** 0.6 | **Max Tokens:** 1500

---

## 13. Crawl Service — Website Scraping Pipeline

**File:** `backend/app/services/crawl_service.py`

### Data Extraction Functions:

| Function | Purpose | Output |
|---|---|---|
| `_extract_meta()` | Title, meta description, H1s, viewport check | `{title, meta_desc, h1s, has_viewport, has_meta}` |
| `_extract_nav_links()` | Internal navigation links (same-domain) | List of URLs (max 30) |
| `_extract_social_links()` | Social media profile links | List of URLs (max 10) |
| `_extract_schema_markup()` | JSON-LD `@type` values | List of strings (max 10) |
| `_detect_tech_signals()` | Technology stack detection (23 patterns) | List of tech names |
| `_extract_cta_patterns()` | Button & CTA text | List of strings (max 10) |
| `_check_sitemap()` | Sitemap.xml reference check | Boolean |
| `_select_pages_to_crawl()` | Pick about/pricing/products/contact/blog pages | List of `{url, type}` (max 5) |

### Tech Stack Detection Patterns:

WordPress, Shopify, Squarespace, Wix, Webflow, React/Next.js, Vue.js, Angular, Gatsby, HubSpot, Mailchimp, Intercom, Drift, Zendesk, Google Analytics, Google Tag Manager, Hotjar, Stripe, Cloudflare, Bootstrap, Tailwind CSS, Calendly, Facebook Pixel

### Crawl Output Structure:

```json
{
  "homepage": {
    "title": "...",
    "meta_desc": "...",
    "h1s": ["..."],
    "nav_links": ["..."]
  },
  "pages_crawled": [
    {"url": "...", "type": "about|pricing|products|contact|blog", "key_content": "..."}
  ],
  "tech_signals": ["React/Next.js", "Google Analytics", "Stripe"],
  "cta_patterns": ["Get Started", "Book a Demo"],
  "social_links": ["https://linkedin.com/..."],
  "schema_markup": ["Organization", "WebPage"],
  "seo_basics": {
    "has_meta": true,
    "has_viewport": true,
    "has_sitemap": false
  }
}
```

---

## 14. LLM Provider Summary

| Step | LLM Provider | Model | Temperature | Max Tokens |
|---|---|---|---|---|
| Early Recommendations | OpenAI | GPT-4o-mini | 0.4 | 1200 |
| Crawl Summary | OpenAI | GPT-4o-mini | 0.3 | 300 |
| Business Intel Verdict | OpenAI | GPT-4o-mini | 0.5 | 2000 |
| RCA Diagnostic (×3-4) | OpenRouter | Claude Sonnet | 0.7 | 900 |
| Precision Questions | OpenRouter | Claude Sonnet | 0.7 | 1200 |
| Tool Recommendations | OpenAI | GPT-4o-mini | 0.4 | 3500 |
| Business Insights | OpenAI | GPT-4o-mini | 0.6 | 1500 |
| Website Audience Analysis | OpenAI | GPT-4o-mini | 0.5 | 1000 |

---

## 15. Session Data Accumulation

The session object accumulates data throughout the flow:

| Stage | Data Added to Session |
|---|---|
| Q1 | `outcome`, `outcome_label` |
| Q2 | `domain` |
| Q3 | `task`, `persona_doc_name`, `rca_diagnostic_context` (problems/RCA bridge/opportunities/strategies from persona docs) |
| Early Recs | `early_recommendations` (cached in session) |
| URL Submit | `website_url`, `url_type` |
| Crawl | `crawl_raw` (full structured data), `crawl_summary` (5 bullets), `crawl_status` |
| Scale Qs | `business_profile` (business_stage, current_stack, primary_channel, biggest_constraint) |
| Business Intel | Rendered to frontend (not stored in session — consumed directly) |
| RCA Diagnostic | `rca_history` (array of `{question, answer}` pairs), `rca_complete`, `rca_summary` |
| Precision Qs | Answered and stored in session (precision question answers) |
| Auth Gate | User name + email collected |
| Final Report | `recommendations` (extensions, gpts, companies), `insights`, `icp_analysis` |

---

*Generated from source code on the current working branch. Last updated: session in progress.*
