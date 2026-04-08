# System Prompt Migration Plan (Runtime Usage Audit)

This document marks each static prompt as one of:
- **ACTIVE**: currently used in runtime flow
- **CONDITIONAL**: used only as fallback/when a branch is hit
- **INACTIVE**: defined but currently has no runtime call path

## 1) Onboarding RCA Prompt

### `_RCA_SYSTEM_PROMPT_DEFAULT`
- **Location:** `backend/app/services/onboarding_crawl_service.py:202`
- **Status:** **CONDITIONAL**
- **Runtime trigger:**
  - Background task `crawl` (`backend/app/task_stream/tasks/onboarding_crawl.py`) calls `generate_rca_questions(...)`
  - `POST /api/v1/onboarding/rca-next-question` may also call `generate_rca_questions(...)` via `onboarding_question_service` when `onboarding.rca_qa` is empty
- **Note:** primary path already uses DB/Redis prompt (`get_prompt("rca-questions", default=...)`); this constant is fallback only.

## 2) Claude RCA Service Prompts

### `TASK_FILTER_SYSTEM_PROMPT`
- **Location:** `backend/app/services/claude_rca_service.py:67`
- **Status:** **INACTIVE**
- **Reason:** only used inside `generate_task_alignment_filter(...)`, and there are no call sites to that function.

### `SYSTEM_PROMPT`
- **Location:** `backend/app/services/claude_rca_service.py:323`
- **Status:** **INACTIVE**
- **Reason:** only used inside `generate_next_rca_question(...)`, and there are no call sites to that function.

### `PRECISION_SYSTEM_PROMPT`
- **Location:** `backend/app/services/claude_rca_service.py:1009`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - `POST /api/v1/onboarding/precision/start` (`backend/app/routers/onboarding.py`) calls `generate_precision_questions(...)`
  - Journey flow also calls `generate_precision_questions(...)` from `backend/app/services/journey_service.py`

## 3) Playbook Service Prompts

### `PHASE0_PROMPT`
- **Location:** `backend/app/services/playbook_service.py:28`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - `POST /api/v1/onboarding/playbook/launch` -> `_prepare_onboarding_playbook(...)` -> `run_phase0_gap_questions(...)`
  - Journey flow also uses `run_phase0_gap_questions(...)`

### `AGENT_A_MERGED_PROMPT`
- **Location:** `backend/app/services/playbook_service.py:236`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Background task `playbook/onboarding-generate` (`backend/app/task_stream/tasks/onboarding_playbook_generate.py`) -> `run_agent_a_merged(...)`

### `AGENT_E_STANDALONE_PROMPT`
- **Location:** `backend/app/services/playbook_service.py:314`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Background task `playbook/onboarding-generate` -> `run_agent_e_standalone(...)`

### `AGENT3_PROMPT`
- **Location:** `backend/app/services/playbook_service.py:72`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Background task `playbook/onboarding-generate` -> `run_agent_c_stream(...)`

## 4) Persona System Prompts (`personas.py`)

### `PRODUCT_PROMPT`, `CONTRIBUTOR_BRIEF_PROMPT`, `CONTRIBUTOR_CHAT_PROMPT_TEMPLATE`, `ASSISTANT_PROMPT`, `DEFAULT_PROMPT`
- **Location:** `backend/app/data/personas.py`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - `openai_service.chat_completion(...)` builds system prompt via `build_system_prompt(...)`
  - Called by `unified_chat_service.run_standard_chat(...)`
  - Reached via:
    - `POST /api/v1/chat`
    - `POST /api/chat` (legacy)
    - `/api/v1/ai-chat/*` standard-chat branches
    - DoableClaw `/api/...` chat paths when request routes to standard mode

## 5) Sheets Service Prompts (passed as system messages)

### `search_prompt`
- **Location:** `backend/app/services/sheets_service.py:313`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - `POST /api/search-companies` (legacy) -> `sheets_service.search_companies(...)` -> `openai_service.company_search_gpt(...)`

### `explanation_prompt`
- **Location:** `backend/app/services/sheets_service.py:500`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - same flow as above, via `_generate_explanation(...)` -> `openai_service.company_explanation_gpt(...)`

## 6) Agent / Skills Pipeline Prompts

### `_SYSTEM_PROMPT` (skill input extractor)
- **Location:** `backend/app/doable_claw_agent/agent/skill_input_extractor.py:11`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Orchestrator calls `extract_skill_args(...)` during agentic runs

### `"You are a strict evidence matcher."`
- **Location:** `backend/app/doable_claw_agent/agent/orchestrator.py:261`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Used by `_mark_checklist_items_from_summary(...)` during orchestrator execution

### Final formatter system strings
- **Location:** `backend/app/doable_claw_agent/agent/final_formatter.py:60,76`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Orchestrator final response synthesis (`format_final_answer(...)`)
  - Also used by plan-execution pipeline in `agent_checklist_service`

### `"You produce faithful, compact summaries for downstream routing."`
- **Location:** `backend/app/doable_claw_agent/agent/skill_call_summarizer.py:32`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Called by orchestrator `build_calls_summary(...)`

### `"You convert web extraction objects into compact factual notes."`
- **Location:** `backend/app/services/agent_checklist_service.py:531,1263`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Plan creation/execution flow when processing scrape page chunks

### `"You are a planning assistant. Output only Markdown. No code fences."`
- **Location:** `backend/app/services/agent_checklist_service.py:795`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - Plan drafting in agent checklist flow (`create_plan_draft` path)

### Skills summarizer system prompts
- **Location:** `backend/app/skills/service.py:333,384,443`
- **Status:** **ACTIVE**
- **Runtime trigger:**
  - `run_skill(...)` summary post-processing for multiple skills (including scrape-related skills)

## Non-runtime files

### `backend/app/services/BACKUP_ORIGINAL_SYSTEM_PROMPT.txt`
- **Status:** not runtime
- **Reason:** backup/reference only.
