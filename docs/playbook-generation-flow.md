# Playbook Generation Flow

## Overview

The playbook generation system uses **3 LLM agents** — 2 running in parallel and 1 streaming sequentially after. All agents use `anthropic/claude-sonnet-4-6` via OpenRouter.

Gap questions are a **separate API** (`POST /gap-questions/start`) that runs before playbook launch. By the time playbook generation starts, `gap_answers` are already stored in the onboarding row.

---

## Pre-requisite: Gap Questions API (separate flow)

**Endpoint:** `POST /gap-questions/start`

**What it does:** Generates up to 3 clarifying multiple-choice questions before the user launches the playbook. Uses `generate_gap_questions()` from `claude_rca_service`.

**Flow:**
```
POST /gap-questions/start
  ↓
  generate_gap_questions() → 0-3 questions
  ↓
  Stored in onboarding.gap_questions (JSON)

User answers questions via POST /playbook/gap-answers
  ↓
  Stored in onboarding.gap_answers (JSON: {"Q1": "A", "Q2": "C"})

POST /playbook/launch
  ↓
  Validates gap_questions is set (error if NULL — "Call /gap-questions/start first")
  Validates gap_answers is filled if questions exist
  ↓
  Triggers onboarding_playbook_generate task
```

**Note:** `_prepare_onboarding_playbook` (old inline path) is explicitly marked deprecated in the router.

---

## Playbook Generation Flow

```
T=0s   Trigger: onboarding_playbook_generate_task(onboarding_id)
         ↓
       DB fetch: onboarding row (outcome, domain, task, scale_answers,
                                  rca_qa, rca_summary, rca_handoff,
                                  gap_answers ← already filled, web_summary)
         ↓
       Create playbook_runs row (status='running')
         ↓
       ┌─────────────────────────────────────────────┐
       │         PARALLEL (asyncio.gather)           │
       │                                             │
       │  Agent A (Context Parser + ICP Analyst)     │
       │  ─────────────────────────────────────      │
       │  Temp: 0.5 | Max tokens: 3000               │
       │  Latency: ~2-3s                             │
       │  Output: Business Context Brief             │
       │                                             │
       │  Agent E (Website Critic)                   │
       │  ─────────────────────────────────────      │
       │  Temp: 0.5 | Max tokens: 5000               │
       │  Latency: ~3-4s (best-effort, can fail)     │
       │  Output: Website Audit                      │
       └─────────────────────────────────────────────┘
         ↓ (wait for Agent A to complete)
       Tools lookup: get_tools_for_q1_q2_q3() → TOON format
         ↓
       Agent C (Playbook Architect) ← STREAMING
       ─────────────────────────────────────────────
       Temp: 0.7 | Max tokens: 10000
       Latency: ~4-5s
       Tokens streamed live to frontend via task_stream
       Output: 10-step Execution Playbook
         ↓
       DB update: playbook_runs (status='complete', playbook, website_audit,
                                  context_brief, latencies)
       DB update: onboarding (playbook_status='complete')
```

---

## Agent A — Context Parser + ICP Analyst

**File:** `playbook_service.py` → `run_agent_a_merged()`

**Runs:** In parallel with Agent E

**Prompt:** `AGENT_A_MERGED_PROMPT`

### Input

| Field | Source | Description |
|---|---|---|
| `outcome` | onboarding row | e.g., "Lead Generation" |
| `domain` | onboarding row | e.g., "B2B SaaS" |
| `task` | onboarding row | Primary goal — NON-NEGOTIABLE |
| `scale_answers` | onboarding row | buying_process, revenue_model, sales_cycle, existing_assets, buyer_behavior, current_stack |
| `rca_qa` | onboarding row | Root cause analysis Q&A pairs (TOON format) |
| `rca_summary` | onboarding row | Narrative findings from RCA |
| `rca_handoff` | onboarding row | Compact structured summary |
| `web_summary` | onboarding row | Website crawl bullet points |
| `gap_answers` | onboarding row | Phase 0 answers |

### Output — Business Context Brief

```markdown
## BUSINESS CONTEXT BRIEF

**COMPANY SNAPSHOT**
- Name, Industry, Business Model, Primary Market, Revenue Model

**GOAL CLASSIFICATION**
- Primary Goal: [MUST match TASK field exactly]
- Task Priority Order + rationale

**BUYER SITUATION**
- Stage: Idea / Early Traction / Growth / Established
- Current Stack, Stack Gap, Channel Strength, Constraint

**WEBSITE INTELLIGENCE**
- Primary CTA, SEO Signals (H1/Meta/Sitemap/Schema Y/N)
- Biggest Website Risk (one conversion killer)

**INFERRED GAPS** (2-3 implied but unstated issues)

**DATA QUALITY**
- Confidence: HIGH / MEDIUM / LOW
- Missing Data

---

**GAP QUESTIONS** (1-2, max 3)
```

**Critical rules:**
- `TASK` field is never overridden by website crawl data
- Does not give advice or build playbooks — only parses and structures

---

## Agent E — Website Critic

**File:** `playbook_service.py` → `run_agent_e_standalone()`

**Runs:** In parallel with Agent A (best-effort — failure does not block Agent C)

**Prompt:** `AGENT_E_STANDALONE_PROMPT`

### Input

| Field | Source | Description |
|---|---|---|
| `outcome` | onboarding row | Growth goal |
| `domain` | onboarding row | Business domain |
| `task` | onboarding row | Primary task |
| `scale_answers` | onboarding row | Business profile |
| `rca_qa` | onboarding row | Diagnostic Q&A |
| `web_summary` | onboarding row | Raw website crawl signals |

**Step 1 (mandatory):** Classify business as B2B or D2C from observable signals before any analysis.

### Output — Website Audit (B2B mode)

```markdown
# Your Website Audit — What Buyers Actually See

## 1. Who's Landing on Your Site
[3-4 lines: buyer profile, role, company size, pain point, buying cycle]

**The Gap**
[Disconnect between what the site says vs what buyers need]

## 2. Your Site's Scorecard
| What We Checked | Score | Finding |
|---|---|---|
| Can they tell what you do in 10 seconds? | X/10 | ... |
| Would a referred prospect "get it"? | X/10 | ... |
| Is there proof for buying committee? | X/10 | ... |
| Can they see how it works? | X/10 | ... |
| Clear next step for serious buyers? | X/10 | ... |

**Overall: X/10**

## 3. The 30-Minute Fix
[Single highest-impact CMS-level change]

## 4. The Big Build
[One developer-worthy change with highest ROI]

## 5. Where Your Site Loses the Sale
[3-5 friction points with revenue impact HIGH/MEDIUM/LOW
 and who it blocks: Economic Buyer / Technical Evaluator /
 Internal Champion / Procurement]
```

D2C mode output follows the same structure but focuses on emotional triggers, mobile experience, impulse psychology, and cart drop-off points.

---

## Agent C — Playbook Architect (Streaming)

**File:** `playbook_service.py` → `run_agent_c_stream()`

**Runs:** After Agent A completes (sequential, blocks on A)

**Prompt:** `AGENT3_PROMPT`

### Input

| Field | Source | Description |
|---|---|---|
| `agent_a_output` | Agent A result | Business Context Brief |
| `gap_answers` | onboarding row | Phase 0 answers |
| `recommended_tools` | `get_tools_for_q1_q2_q3()` | TOON-formatted tool list (up to 10) |
| `task` | onboarding row | Locked focus — every step must serve this |

### Output — 10-Step Execution Playbook

```markdown
THE "[OUTCOME IN CAPS]" PLAYBOOK

[2-3 lines: The One Lever — single unlock for the entire playbook]

---

1. [PRIORITY: HIGH] The "[Memorable Step Name]"

WHAT TO DO
[2-3 lines: specific action, founder-friendly tone]

TOOL + AI SHORTCUT
[Tool name] — [one-line how to use]
Prompt: "[Exact copy-paste prompt specific to THIS company and ICP]"

REAL EXAMPLE
[Actual brand/company from their industry — 2-3 lines]

THE EDGE
"[Technique name]": [timing trick, psychology angle, or tactical detail]

[Steps 2–10 in same format — always exactly 10]

---

WEEK 1 EXECUTION CHECKLIST
Monday: [specific action]
Tuesday: [specific action]
Wednesday: [specific action]
Thursday: [specific action]
Friday: [specific action]

"[One closing sentence — truth, not pitch]"
```

**Non-negotiable rules:**
- Exactly 10 steps, no more, no less
- Every step names a technique in quotes + PRIORITY label
- Steps form a chain — each builds on the last
- Simple English — readable on a phone at 10pm
- Every step must be specific to THIS company (not generic)

**Streaming:** Tokens are sent to the frontend in real-time via `send("token", token=token)` as they arrive from the model.

---

## TOON Format (Token Optimization)

All agent inputs use a compact serialization format to reduce token usage by 35–55%.

```
# Inline pairs
PROFILE{key:value|key:value}

# Tabular (RCA Q&A)
RCA[3]{question|answer}:
What is your target market?|B2B SaaS founders
How do you currently generate leads?|Referrals only
What's your sales cycle?|3-6 months

# Tools table
TOOLS[5]{name|type|price|desc|why|solves|ease}:
Apollo.io|prospecting|Free/Paid|Lead database|Strong B2B signals|No qualified list|1hr setup
```

---

## Timing & Critical Path

```
T=0s    Task starts
T=1s    DB fetch + playbook_runs row created
T=1s    Agent A + Agent E start (parallel)
T=3-4s  Agent A completes → unblocks Agent C
T=3-4s  Agent C starts streaming tokens to frontend
T=4-8s  Agent E completes (background, non-blocking)
T=7-9s  Agent C finishes streaming
T=9-10s DB updated, task complete

Critical path: fetch(1s) → Agent A(2-3s) → Agent C(4-5s) → save(1s)
                                                 ↑ ~8-10s total
```

---

## Database

### `playbook_runs` table (output snapshot)

| Column | Value |
|---|---|
| `status` | `running` → `complete` / `error` |
| `context_brief` | Agent A full output |
| `icp_card` | `""` (empty for now) |
| `playbook` | Agent C full 10-step playbook |
| `website_audit` | Agent E full audit |
| `latencies` | `{ agent_a: ms, agent_c: ms, agent_e: ms }` |
| `error` | Error message if failed |

### `onboarding` table (status update)

| Column | Value |
|---|---|
| `playbook_status` | `complete` |
| `playbook_completed_at` | timestamp |
| `onboarding_completed_at` | timestamp (if not already set) |

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Agent E fails | Logged, returns `""`, playbook continues unblocked |
| Agent A fails | Raises exception, blocks Agent C, task marked `error` |
| Agent C fails | Exception caught, `playbook_runs.status = 'error'` |
| DB error | Caught and persisted to `playbook_runs.error` |