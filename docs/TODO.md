# TODO

> **Created:** April 8, 2026

---

## Harsh

- [ ] API endpoint to fetch playbook content from DB (~2h)
  - `GET /api/v1/onboarding/playbook?session_id=xxx`
  - Auth: JWT `user_id` if available, fallback to `session_id`
  - Query `playbook_runs`, return `{ content, status, playbookData }`

- [ ] Add `type` field to config values + validation (~1h)
  - Types: `string`, `number`, `boolean`, `json`, `markdown`
  - Backend validates value against type on save

- [ ] Research agent execution duration tracking (~2h)
  - Track checkpoints: `approved_at`, `first_token_at`, `completed_at`
  - Store in database for future analysis

- [ ] Move all LLM system prompts into `system_config` DB table (~4h)
  - Identify all hardcoded system prompts in backend services
  - Add config entries with `type: "markdown"` for prompts

- [ ] Create prompts repository service (~3h)
  - Backend functions can read any prompt via slug/key
  - Cache prompts in Redis with 1 hour TTL
  - Auto-refresh from DB when cache expires

---

## Rohit

- [ ] Attach onboarding row to conversation row (~2h)
  - (Already implemented - needs testing, bug fixes, deploy & verify)

- [ ] Frontend playbook restoration + reset logic (~1h)
  - Reset flow works for both session-based and JWT-based
  - If "generating": fetch partial + resume stream
  - If "completed": show full playbook + "Start New Journey" button
  - Call `clearSession()` + navigate to outcome selection

- [ ] Add interactive context editor for markdown config values (~1h)
  - Reuse existing context editor component from agents
  - Show editor in admin config page when `type` is `markdown`

- [ ] Token usage tracking - Backend + Frontend (~6h)
  - Backend: Store token metadata in `token_usage` table
  - Fields: `conversation_id`, `user_id`, `model`, `input_tokens`, `output_tokens`, `cost`
  - APIs: overall spend, users list, user conversations, conversation LLM calls
  - Frontend: Admin page with spend + users list → user detail → conversation side panel

- [ ] Send research report link via SMS (~2h)
  - Send conversation link after report completes
  - Only if user has phone number
  - Add system config toggle to enable/disable
