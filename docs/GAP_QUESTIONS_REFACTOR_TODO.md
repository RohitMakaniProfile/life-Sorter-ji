# Gap Questions Refactor — Move to Separate API

## Goal
Separate gap questions into a dedicated POST endpoint that runs **before** playbook launch. This enables:
1. Frontend to show animated transition messages while playbook generation starts in background
2. Better UX flow similar to RCA/precision questions
3. Parallel execution: gap questions check completes → playbook starts immediately → frontend shows transition messages

## Reference Pattern: `POST /precision/start`
Follow the exact same pattern as `POST /precision/start` endpoint in `onboarding.py`:
- Reads all context from onboarding table
- Uses `prompts_service.get_prompt("gap-questions", default=...)` for system prompt
- Generates questions via LLM call
- Stores results in existing `onboarding.gap_questions` field
- Returns questions array (empty if none needed)

## Current Flow
```
POST /playbook/launch
        │
        ▼
_prepare_onboarding_playbook()  ← Phase 0 runs HERE (blocking)
        │
        ├── Has questions? → Return stage="gap_questions" → WAIT
        │
        └── No questions? → Start task stream
```

## Proposed Flow
```
POST /gap-questions/start  ← Runs Phase 0 (like /precision/start)
        │
        ├── Returns questions[] → Frontend shows questions, user answers
        │                         POST /gap-answers (existing)
        │                         Then proceed to playbook
        │
        └── Returns [] (empty) → Frontend:
                                  1. IMMEDIATELY call POST /playbook/launch (no gap check)
                                  2. Show animated messages sequence:
                                     - "Agent has no more questions..."
                                     - "Now has a clear picture of your business..."
                                     - "Defining solution in a formatted playbook..."
                                  3. After messages complete → Show playbook generation UI
                                     (which is already generating/streaming)
```

---

## Phase 1: Backend — Create `POST /gap-questions/start` Endpoint

### Task 1.1: Add "gap-questions" prompt to prompts table
**Action:** Insert prompt via admin UI or migration

- [x] Add prompt with slug `"gap-questions"`
- [x] Content = existing `PHASE0_PROMPT` from `playbook_service.py`
- [x] Category = `"onboarding"` or `"playbook"`

### Task 1.2: Create gap questions generator function
**File:** `backend/app/services/claude_rca_service.py` (or new file)

- [x] Create `generate_gap_questions()` function following `generate_precision_questions()` pattern
- [x] Use `get_prompt("gap-questions", default=_GAP_QUESTIONS_PROMPT_DEFAULT)`
- [x] Call OpenRouter with context payload
- [x] Parse response into questions list

### Task 1.3: Create `POST /gap-questions/start` endpoint
**File:** `backend/app/routers/onboarding.py`

- [x] Add request/response models (GapQuestionItem, StartGapQuestionsRequest, StartGapQuestionsResponse)
- [x] Create endpoint following `/precision/start` pattern
- [x] Resolves `onboarding_id`, fetches context, calls `generate_gap_questions()`
- [x] Updates `onboarding.gap_questions` and `playbook_status`
- [x] Returns questions array (empty if none needed)

### Task 1.4: Update existing `POST /playbook/gap-answers`
**File:** `backend/app/routers/onboarding.py`

- [x] Verified — still works with new flow (unchanged)
- [x] Marks questions as answered after submission

---

## Phase 2: Backend — Modify `/playbook/launch`

### Task 2.1: Remove Phase 0 call from `/playbook/launch`
**File:** `backend/app/routers/onboarding.py`

- [x] Modify `onboarding_playbook_launch()` to NOT call `_prepare_onboarding_playbook()`
- [x] Instead, check `onboarding.gap_questions`:
  - If `NULL` → return error "Call /gap-questions/start first"
  - If `[]` (empty array) → proceed to start task stream
  - If has questions AND `gap_answers` is empty → return error "Answer gap questions first"
  - If has questions AND `gap_answers` filled → proceed to start task stream

### Task 2.2: Deprecate or simplify `_prepare_onboarding_playbook()`
**File:** `backend/app/routers/onboarding.py`

- [x] Marked function as DEPRECATED with warnings
- [x] Added docstring explaining new flow
- [x] Function still exists for backward compatibility but is no longer called

---

## Phase 3: Frontend — New Gap Questions Step

### Task 3.1: Create gap questions API call
**File:** `frontend/src/api/` or equivalent

- [x] Add `startGapQuestions(onboardingId)` API function → `POST /gap-questions/start`
- [x] Handle response: questions array or empty

### Task 3.2: Create GapQuestions component/step
**File:** `frontend/src/components/` or `frontend/src/pages/`

- [x] New component for displaying gap questions (similar to precision questions UI)
  - Note: Gap questions reuse existing PlaybookStage component with showGapQuestions prop
- [x] Form for answering questions
- [x] Submit answers via existing `POST /playbook/gap-answers`

### Task 3.3: Create transition messages component
**File:** `frontend/src/components/`

- [x] Animated message sequence component (`TransitionMessages.jsx`)
- [x] Messages with timeouts:
  ```
  [0ms]    "Agent has no more questions..."
  [1500ms] "Now has a clear picture of your business..."
  [3000ms] "Defining your personalized growth playbook..."
  [4500ms] → Show playbook generation UI
  ```
- [x] Should be interruptible (if playbook completes early, skip to result)

### Task 3.4: Update onboarding flow state machine
**File:** `frontend/src/` (wherever flow state is managed)

- [x] Add new state: `checkingGapQuestions`
- [x] Add new state: `showTransitionMessages`
- [x] Flow: `precision_complete` → `checking_gap_questions` → `gap_questions` OR `transition_messages` → `playbook_generating`

### Task 3.5: Parallel execution logic
**File:** `frontend/src/` (playbook page/component)

- [x] When `POST /gap-questions/start` returns empty:
  1. Immediately call `POST /playbook/launch` (fire and forget or track)
  2. Start transition messages animation
  3. After animation completes, show playbook generation UI
  4. Connect to SSE stream for tokens (already running in background)

---

## Phase 4: Edge Cases & Polish

### Task 4.1: Handle edge cases
- [x] User refreshes during transition messages → check playbook_status, resume appropriately
  - Note: Session restore already handles `playbook_status === 'generating'` by reconnecting to stream
- [x] Playbook completes before messages finish → option to skip to result
  - Note: TransitionMessages component checks `isComplete` prop and calls `onComplete` early
- [ ] Network error during gap-questions call → retry logic
- [x] Gap questions already answered (user goes back) → skip to playbook
  - Note: Session restore handles `playbook_status === 'awaiting_gap_answers'` case

### Task 4.2: Add loading states
**File:** `frontend/src/components/`

- [x] Loading spinner while fetching gap questions (`checkingGapQuestions` state)
- [x] Disable buttons during API calls (handled via loading states)
- [ ] Error states with retry options

---

## Phase 5: Testing & Cleanup

### Task 5.1: Backend tests
- [ ] Test POST /gap-questions/start returns questions when needed
- [ ] Test POST /gap-questions/start returns empty when context is sufficient
- [ ] Test /playbook/launch rejects if gap questions not checked
- [ ] Test /playbook/launch proceeds when gap questions answered

### Task 5.2: Frontend tests
- [ ] Test gap questions flow end-to-end
- [ ] Test transition messages timing
- [ ] Test parallel execution (launch called immediately)

### Task 5.3: Cleanup
- [ ] Remove Phase 0 code from `_prepare_onboarding_playbook()`
- [ ] Move `PHASE0_PROMPT` to prompts table (delete from `playbook_service.py`)
- [ ] Update documentation

---

## Implementation Order (Recommended)

1. **Task 1.1** — Add prompt to DB
2. **Task 1.2** — Create generator function
3. **Task 1.3** — Create `/gap-questions/start` endpoint
4. **Task 2.1-2.2** — Modify `/playbook/launch`
5. **Task 3.1-3.2** — Frontend API + Component
6. **Task 3.3-3.5** — Frontend flow changes
7. **Phase 4** — Edge cases
8. **Phase 5** — Testing & cleanup

---

## API Contract Summary

### POST /gap-questions/start
```json
// Request
{ "onboarding_id": "uuid" }

// Response when questions needed
{
  "onboarding_id": "uuid",
  "questions": [
    {
      "id": "Q1",
      "label": "Sales Channel",
      "question": "What is your primary sales channel?",
      "why_matters": "Determines outreach strategy in playbook",
      "options": ["Direct sales", "Marketplace", "Referrals", "Other"]
    }
  ],
  "available": true
}

// Response when no questions needed
{
  "onboarding_id": "uuid",
  "questions": [],
  "available": false
}
```

### POST /playbook/launch (modified behavior)
```json
// Request
{ "onboarding_id": "uuid" }

// Response (success)
{
  "onboarding_id": "uuid",
  "stage": "started",
  "stream_id": "uuid",
  "message": "Playbook generation started."
}

// Response (error - gap questions not checked)
{
  "detail": "Call /gap-questions/start before launching playbook."
}

// Response (error - gap questions unanswered)  
{
  "detail": "Answer gap questions before launching playbook."
}
```

---

## Existing DB Fields Used (No Migration Needed)

| Field | Type | Usage |
|-------|------|-------|
| `onboarding.gap_questions` | JSONB | Stores generated questions |
| `onboarding.gap_answers` | TEXT | Stores user answers |
| `onboarding.playbook_status` | TEXT | Tracks playbook state |

---

## Notes

- **No new columns needed** — use existing `gap_questions` field
- Follow exact pattern of `/precision/start` endpoint
- Use `prompts_service.get_prompt("gap-questions")` for prompt management
- `PHASE0_PROMPT` moves from code to prompts table
- Parallel execution gives ~3-5 seconds of "perceived instant" response
