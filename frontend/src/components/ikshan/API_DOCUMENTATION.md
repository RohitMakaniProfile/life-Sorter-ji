# Ikshan Clawbot UI — Backend API Documentation

> Base URL: `/api/v1/agent`
> All endpoints are proxied via Vite config: `/api` → `http://127.0.0.1:8000`

---

## Flow Overview

```
Create Session → Q1 (Outcome) → Q2 (Domain) → Q3 (Task)
    → URL Submit/Skip → Crawl Status (poll)
    → Scale Questions → Submit Scale Answers
    → Start Diagnostic → Submit Answers (loop)
    → Precision Questions → Submit Answers (loop)
    → Recommendations (final)
```

---

## 1. Session Management

### `POST /api/v1/agent/session`
Create a new user session.

**Request Body:** _none_

**Response:**
```json
{
  "session_id": "uuid-string",
  "stage": "init"
}
```

**Frontend Usage:** Called once via `ensureSession()` — lazy-initialized on first user interaction.

---

## 2. Q1 → Q2 → Q3 Selection

### `POST /api/v1/agent/session/outcome`
Record Q1: Outcome / Growth Bucket selection.

**Request Body:**
```json
{
  "session_id": "uuid",
  "outcome": "lead-generation",
  "outcome_label": "Lead Generation (Marketing, SEO & Social)"
}
```

**Response:** `{ "session_id": "...", "stage": "outcome_set" }`

---

### `POST /api/v1/agent/session/domain`
Record Q2: Domain / Sub-Category selection.

**Request Body:**
```json
{
  "session_id": "uuid",
  "domain": "Content & Social Media"
}
```

**Response:** `{ "session_id": "...", "stage": "domain_set" }`

---

### `POST /api/v1/agent/session/task`
Record Q3: Task selection. Loads persona docs, generates early tool recommendations, and creates first adaptive RCA question via Claude.

**Request Body:**
```json
{
  "session_id": "uuid",
  "task": "Generate social media posts captions & hooks"
}
```

**Response:**
```json
{
  "session_id": "...",
  "stage": "task_set",
  "persona_loaded": "Content & Social Media",
  "task_matched": "...",
  "questions": [{ "question": "...", "options": [...], "allows_free_text": true }],
  "rca_mode": true,
  "acknowledgment": "...",
  "insight": "...",
  "early_recommendations": [
    { "name": "Canva", "description": "...", "url": "...", "category": "content-creation", "rating": 4.75, "why_relevant": "..." }
  ],
  "early_recommendations_message": "..."
}
```

**Note:** Tool recommendations on the frontend are now handled locally via `toolService.js` using `tools_by_q1_q2_q3.json` — no backend call needed for tool display. The backend call is fire-and-forget for session tracking only.

---

## 3. URL & Website Crawl

### `POST /api/v1/agent/session/url`
Submit user's business URL for crawling and analysis.

**Request Body:**
```json
{
  "session_id": "uuid",
  "business_url": "https://example.com",
  "gbp_url": ""
}
```

**Response:**
```json
{
  "session_id": "...",
  "url": "https://example.com",
  "url_type": "business",
  "crawl_started": true
}
```

---

### `POST /api/v1/agent/session/skip-url`
Skip the URL submission step.

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response:** `{ "session_id": "...", "skipped": true }`

---

### `GET /api/v1/agent/session/{session_id}/crawl-status`
Poll for website crawl progress.

**Response:**
```json
{
  "session_id": "...",
  "crawl_status": "completed",
  "crawl_summary": { ... }
}
```

---

## 4. Scale Questions (Business Context / Deeper Dive)

### `GET /api/v1/agent/session/{session_id}/scale-questions`
Fetch scale/slider questions for business context gathering.

**Response:**
```json
{
  "questions": [
    {
      "id": "q1",
      "question": "How would you rate your current...",
      "options": ["1", "2", "3", "4", "5"],
      "multi_select": false
    }
  ]
}
```

---

### `POST /api/v1/agent/session/scale-answers`
Submit all scale question answers.

**Request Body:**
```json
{
  "session_id": "uuid",
  "answers": {
    "q1": "3",
    "q2": ["option_a", "option_b"]
  }
}
```

**Response:** `{ "session_id": "...", "stage": "scale_complete" }`

---

## 5. Diagnostic (RCA) Questions

### `POST /api/v1/agent/session/start-diagnostic`
Start the adaptive diagnostic question flow (Claude-powered RCA).

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response:**
```json
{
  "session_id": "...",
  "question": {
    "question": "What is the biggest bottleneck...",
    "options": ["Manual data entry", "Slow approvals", ...],
    "allows_free_text": true,
    "section": "rca",
    "section_label": "Diagnostic"
  }
}
```

---

### `POST /api/v1/agent/session/answer`
Submit an answer to the current diagnostic/precision question.

**Request Body:**
```json
{
  "session_id": "uuid",
  "question_index": 0,
  "answer": "Manual data entry"
}
```

**Response (more questions):**
```json
{
  "all_answered": false,
  "next_question": {
    "question": "...",
    "options": [...],
    "allows_free_text": true
  }
}
```

**Response (all done):**
```json
{
  "all_answered": true,
  "next_question": null
}
```

---

## 6. Precision Questions

### `POST /api/v1/agent/session/precision-questions`
Generate precision questions based on diagnostic answers (contradiction/blind-spot detection).

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response:**
```json
{
  "available": true,
  "questions": [
    {
      "type": "contradiction",
      "question": "You mentioned X but your website shows Y...",
      "options": ["Yes", "No", "Partially", "Not sure"],
      "section_label": "Precision",
      "insight": "We noticed a gap between..."
    }
  ]
}
```

---

## 7. Final Recommendations

### `POST /api/v1/agent/session/recommend`
Generate final personalized tool recommendations.

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response:**
```json
{
  "session_id": "...",
  "recommendations": {
    "tools": [...],
    "playbook": "...",
    "summary": "..."
  }
}
```

---

## Frontend API Module

All API calls are centralized in `api.js`:

| Function | Endpoint | Method | Used In |
|---|---|---|---|
| `createSession()` | `/session` | POST | `ensureSession()` — lazy init |
| `submitOutcome(sid, outcome, label)` | `/session/outcome` | POST | `handleOutcomeClick` |
| `submitDomain(sid, domain)` | `/session/domain` | POST | `handleDomainClick` |
| `submitTask(sid, task)` | `/session/task` | POST | `handleTaskClick` (fire-and-forget) |
| `submitUrl(sid, url)` | `/session/url` | POST | `handleUrlSubmit` |
| `skipUrl(sid)` | `/session/skip-url` | POST | `handleUrlSkip` |
| `getCrawlStatus(sid)` | `/session/{id}/crawl-status` | GET | crawl polling |
| `getScaleQuestions(sid)` | `/session/{id}/scale-questions` | GET | `moveToScaleQuestions` |
| `submitScaleAnswers(sid, answers)` | `/session/scale-answers` | POST | `handleScaleSubmit` |
| `startDiagnostic(sid)` | `/session/start-diagnostic` | POST | `handleScaleSubmit` |
| `submitAnswer(sid, idx, answer)` | `/session/answer` | POST | `handleDiagnosticAnswer`, `handlePrecisionAnswer` |
| `getPrecisionQuestions(sid)` | `/session/precision-questions` | POST | after diagnostic complete |
| `getRecommendations(sid)` | `/session/recommend` | POST | final step |

---

## Notes

- **DEMO_MODE:** When `DEMO_MODE = true` in `IkshanApp.jsx`, all LLM-dependent calls (diagnostic, precision, recommendations) are bypassed with hardcoded dummy data. Set to `false` for production.
- **Tool Lookup:** Done entirely on the frontend via `toolService.js` using local `data/tools_by_q1_q2_q3.json`. No backend API call needed.
- **Environment Variable:** `VITE_API_URL` can override the API base URL. Defaults to empty string (same-origin proxy).
