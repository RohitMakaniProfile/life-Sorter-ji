# Phase 1 Simplification Proposal

## Goal

Simplify the pre-login agent flow and reduce backend/frontend complexity by:

- reducing endpoint count
- centralizing workflow transitions
- minimizing duplicated frontend orchestration logic
- keeping Google sign-in handoff and conversation promotion intact

## Current Problems

The current flow is split across many small step endpoints (outcome/domain/task/answer/url/scale/diagnostic/precision/recommend), which causes:

- too many network round trips
- duplicated orchestration logic in frontend components
- workflow transitions spread across multiple backend handlers
- harder observability and debugging of session progression

## Proposed API Surface (Simplified)

### 1) Create session

- `POST /api/v1/agent/session`
- Responsibility: initialize a session and return `session_id`.

### 2) Generic state update

- `PATCH /api/v1/agent/session/{id}`
- Responsibility: update simple fields in session state.
- Typical payload fields:
  - `outcome`
  - `outcome_label`
  - `domain`
  - `task`
  - `business_url` / `gbp_url`
  - `scale_answers`
  - `skip_url`
  - `dynamic_answer` (if applicable)

### 3) Advance workflow

- `POST /api/v1/agent/session/{id}/advance`
- Responsibility: run the next heavy workflow step based on current state/stage.
- Handles:
  - first or next diagnostic question generation
  - precision question generation
  - recommendation generation
  - crawl trigger/continuation logic (if required)

### 4) Session snapshot

- `GET /api/v1/agent/session/{id}`
- Responsibility: return canonical full session state for UI hydration.

### 5) Optional progress/status endpoint

- `GET /api/v1/agent/session/{id}/status` (or `/events`)
- Responsibility: lightweight progress/crawl status polling or event stream.

## Target State Model

Use one canonical session object (persisted in `user_sessions`) with grouped fields:

- `profile`
  - outcome/domain/task/scale/auth/url metadata
- `diagnostic`
  - stage, current question, question index, answer history
- `artifacts`
  - crawl summary, precision questions, recommendations
- `meta`
  - created/updated timestamps, version, trace identifiers

This avoids endpoint-specific scattered updates and makes replay/debug easier.

## Frontend Simplification

Move UI orchestration to a simple loop:

1. collect local input
2. `PATCH` session with new fields
3. call `/advance`
4. render returned state/snapshot
5. repeat until completion

Frontend should rely on server state instead of maintaining many parallel local flags.

## Auth Handoff (Google Sign-In)

Keep existing auth endpoints (`/api/v1/auth/google`, `/api/v1/auth/me`) but align handoff behavior:

- link anonymous `session_id` to authenticated `user_id/email`
- promote/migrate conversation ownership
- continue same session context after login

## Migration Strategy (Non-Breaking)

1. Introduce new `PATCH` + `advance` endpoints behind current APIs.
2. Route old step-specific handlers internally to shared orchestration logic.
3. Migrate frontend calls (`ChatBotNew`, `ChatBotNewMobile`) to new contract.
4. Validate parity with existing flows and DB writes.
5. Deprecate and remove old step-specific endpoints.

## Expected Benefits

- fewer APIs to maintain
- cleaner backend state machine boundaries
- reduced frontend complexity and duplicate code
- easier testing and observability
- simpler future feature additions

API simplification count: replaces approximately 15 current agent session endpoints with 5 consolidated endpoints.

