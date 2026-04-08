# Production Readiness Review - Test Cases Checklist

> **Last Updated:** April 8, 2026  
> **System:** Life Sorter / Ikshan AI Platform  
> **Status:** 🔴 Not Started | 🟡 In Progress | 🟢 Passed | ⚪ N/A

---

## Table of Contents

1. [Authentication & Authorization](#1-authentication--authorization)
2. [Onboarding Flow](#2-onboarding-flow)
3. [AI Chat System](#3-ai-chat-system)
4. [Research Orchestrator & Plan Execution](#4-research-orchestrator--plan-execution)
5. [Task Stream System](#5-task-stream-system)
6. [Payment & Subscription](#6-payment--subscription)
7. [Admin Features](#7-admin-features)
8. [API Security & Performance](#8-api-security--performance)
9. [Frontend UI/UX](#9-frontend-uiux)
10. [Database & Data Integrity](#10-database--data-integrity)
11. [Error Handling & Recovery](#11-error-handling--recovery)
12. [External Integrations](#12-external-integrations)
13. [Deployment & Infrastructure](#13-deployment--infrastructure)

---

## 1. Authentication & Authorization

### 1.1 Google OAuth Login
- [ ] 🔴 User can login via Google OAuth successfully
- [ ] 🔴 New user account is created on first Google login
- [ ] 🔴 Existing user account is updated (not duplicated) on subsequent Google logins
- [ ] 🔴 JWT token is generated with correct claims (sub, email, name, avatar_url)
- [ ] 🔴 JWT token expiration is set correctly (7 days)
- [ ] 🔴 Invalid/expired JWT returns 401 Unauthorized
- [ ] 🔴 Google login with existing phone-verified account links accounts correctly
- [ ] 🔴 Google login page can update existing user (via JWT) instead of creating new

### 1.2 Phone OTP Login
- [ ] 🔴 OTP is sent successfully via SMS
- [ ] 🔴 OTP is stored in PostgreSQL (not Redis) correctly
- [ ] 🔴 OTP verification succeeds with correct code
- [ ] 🔴 OTP verification fails with incorrect code
- [ ] 🔴 OTP expires after configured time
- [ ] 🔴 Rate limiting prevents OTP spam
- [ ] 🔴 New user account created on first phone verification
- [ ] 🔴 Session ID from onboarding is linked to user account on verification
- [ ] 🔴 JWT passed during verify updates existing user with phone number (not create new)
- [ ] 🔴 Session ID is removed from localStorage after successful token receipt

### 1.3 Authorization & Access Control
- [ ] 🔴 Protected routes require valid JWT
- [ ] 🔴 Admin routes check admin flag in JWT
- [ ] 🔴 Super admin routes check super flag in JWT
- [ ] 🔴 Admin phone numbers list is checked for admin access
- [ ] 🔴 Unauthenticated requests to protected endpoints return 401
- [ ] 🔴 Insufficient permission requests return 403

### 1.4 Logout
- [ ] 🔴 Logout button redirects to phone number login page
- [ ] 🔴 JWT token is cleared from localStorage
- [ ] 🔴 No auto-redirect back to home page after logout

---

## 2. Onboarding Flow

### 2.1 Session Management
- [ ] 🔴 New session ID is generated if none exists
- [ ] 🔴 Session ID is persisted in localStorage
- [ ] 🔴 `ensureSession` correctly returns session ID for selections
- [ ] 🔴 Completed onboarding session is deleted from localStorage
- [ ] 🔴 Backend creates new onboarding row (not update) if existing row is completed
- [ ] 🔴 User ID from JWT is used for onboarding row if available

### 2.2 State Restoration on Refresh
- [ ] 🔴 `/api/v1/onboarding/state` API returns correct state
- [ ] 🔴 State with outcome/domain/task restores directly to URL stage
- [ ] 🔴 State with scale_answers restores to scale questions stage
- [ ] 🔴 State with rca_qa restores to RCA/diagnostic questions stage
- [ ] 🔴 State with playbook_status=completed shows playbook
- [ ] 🔴 `[Onboarding Restore] No state to restore` only shows when truly empty
- [ ] 🔴 Completed onboarding (`completed_at` set) triggers session deletion and fresh start

### 2.3 Outcome/Domain/Task Selection
- [ ] 🔴 Outcome selection updates state correctly
- [ ] 🔴 Domain selection updates state correctly
- [ ] 🔴 Task selection updates state correctly
- [ ] 🔴 Selection persists across page refresh

### 2.4 URL Stage
- [ ] 🔴 Website URL input accepts valid URLs
- [ ] 🔴 Invalid URL shows appropriate error
- [ ] 🔴 Crawl task stream starts successfully
- [ ] 🔴 Crawl errors remove task stream from localStorage
- [ ] 🔴 Task completion removes stream from localStorage

### 2.5 Scale Questions
- [ ] 🔴 All 6 scale questions display correctly
- [ ] 🔴 Questions display vertically (2 per row as per design)
- [ ] 🔴 Questions have proper card background styling
- [ ] 🔴 Scale answers are saved to backend
- [ ] 🔴 Back button navigates to previous stage

### 2.6 RCA/Diagnostic Questions
- [ ] 🔴 Diagnostic questions display with correct styling (same as scale questions)
- [ ] 🔴 Questions have card background and question text background
- [ ] 🔴 RCA answers are saved to backend
- [ ] 🔴 State restoration works after answering RCA questions
- [ ] 🔴 Back button to scale questions exists and works
- [ ] 🔴 Options are loaded/displayed correctly on refresh

### 2.7 Playbook Generation
- [ ] 🔴 Playbook generation task stream starts correctly
- [ ] 🔴 Playbook content streams and displays progressively
- [ ] 🔴 Playbook is stored in database
- [ ] 🔴 Playbook content is attached to messages via middleware/processor
- [ ] 🔴 PlaybookViewer component renders playbook correctly
- [ ] 🔴 "Do Deep Analysis" button appears at end of playbook
- [ ] 🔴 Deep analysis button creates new conversation with research-orchestrator agent
- [ ] 🔴 Initial message includes website URL from onboarding context

### 2.8 UI/UX Elements
- [ ] 🔴 Arrow SVG between task and URL box is straight (not dashed)
- [ ] 🔴 Dashed arrow SVG has proper design (filled triangle head, wider dashes)
- [ ] 🔴 Arrow reaches left edge of screen and right edge (head) touches question box
- [ ] 🔴 Arrow line stretches horizontally, head does not stretch
- [ ] 🔴 All arrows are fully white without opacity
- [ ] 🔴 Arrow line starts from middle of task box

---

## 3. AI Chat System

### 3.1 Conversation Management
- [ ] 🔴 New conversation creates successfully with valid agent_id
- [ ] 🔴 Conversation list loads correctly
- [ ] 🔴 Messages are saved and retrieved correctly
- [ ] 🔴 Conversation deletion works (agent_id not set to null incorrectly)
- [ ] 🔴 Deleting custom agent doesn't affect research-orchestrator

### 3.2 Agent Selection
- [ ] 🔴 Agent selection layer displays on new chat
- [ ] 🔴 Agent access is checked against user's plan
- [ ] 🔴 Paid/upgrade required badge shows for restricted agents
- [ ] 🔴 Free agents are accessible without subscription
- [ ] 🔴 Research agent requires 499 plan subscription

### 3.3 Message Streaming
- [ ] 🔴 Message streaming works correctly via SSE
- [ ] 🔴 Streaming content displays progressively
- [ ] 🔴 Stream errors are handled gracefully
- [ ] 🔴 Stream can be cancelled by user

### 3.4 Message Display
- [ ] 🔴 Assistant messages render without "insights is not defined" error
- [ ] 🔴 User messages display correctly
- [ ] 🔴 Playbook content in messages uses PlaybookViewer
- [ ] 🔴 Plan messages show approve/cancel OR edit todo/start working consistently

### 3.5 Special Options (Agent Redirect)
- [ ] 🔴 Options can specify `newConversation: true` with `agentId`
- [ ] 🔴 Option click creates new conversation with specified agent
- [ ] 🔴 Initial message context from previous conversation is passed

---

## 4. Research Orchestrator & Plan Execution

### 4.1 Access Control
- [ ] 🔴 Research agent requires 499 plan subscription
- [ ] 🔴 `/api/v1/ai-chat/agent-access` correctly checks plan
- [ ] 🔴 Unauthorized users cannot create research agent conversations
- [ ] 🔴 Payment flow redirects to agent new chat on success

### 4.2 Plan Generation
- [ ] 🔴 Research orchestrator generates execution plan
- [ ] 🔴 Plan is stored in database
- [ ] 🔴 Plan message displays with edit/start working options

### 4.3 Plan Execution
- [ ] 🔴 "Start Working" button initiates plan execution
- [ ] 🔴 Plan execution uses task stream (not polling)
- [ ] 🔴 Background execution returns `taskStream` metadata in response
- [ ] 🔴 Frontend starts streaming to task stream from metadata
- [ ] 🔴 Cancel button appears during execution
- [ ] 🔴 Skills execute sequentially
- [ ] 🔴 Final LLM call generates report

### 4.4 Plan Execution Recovery
- [ ] 🔴 Backend detects stuck processes on startup
- [ ] 🔴 Running tasks with no actual process are marked as interrupted/failed
- [ ] 🔴 `plan_runs` table accepts 'interrupted' status
- [ ] 🔴 Interrupted plans show retry button
- [ ] 🔴 Retry button works and starts fresh execution
- [ ] 🔴 Fresh "Start Working" clears all previous stream IDs
- [ ] 🔴 Fresh start marks all previous background tasks as failed/stopped
- [ ] 🔴 No polling on plan-status (use task stream instead)

### 4.5 Plan Status Display
- [ ] 🔴 Executing status shows progress
- [ ] 🔴 Completed status shows results
- [ ] 🔴 Error/interrupted status shows error message and retry option
- [ ] 🔴 Stream data from localStorage/DB doesn't show stale running state

### 4.6 Deep Dive Component
- [ ] 🔴 "< Back to Tools" button appears at mid-bottom of page
- [ ] 🔴 Button navigates back to tools/home page

---

## 5. Task Stream System

### 5.1 Stream Lifecycle
- [ ] 🔴 Task stream starts with unique stream ID
- [ ] 🔴 Events are published to stream correctly
- [ ] 🔴 Stream cursor tracking works
- [ ] 🔴 Stream completion is detected
- [ ] 🔴 Stream errors are captured and reported

### 5.2 Stream Resumption
- [ ] 🔴 Streams persist across page refresh
- [ ] 🔴 Frontend resumes stream from cursor
- [ ] 🔴 404 on `/task-stream/events` removes stream from localStorage
- [ ] 🔴 Completed/failed streams are cleaned from localStorage

### 5.3 Stream Cleanup
- [ ] 🔴 Playbook generation completion cleans stream
- [ ] 🔴 Crawl completion cleans stream
- [ ] 🔴 Error state cleans stream
- [ ] 🔴 No orphaned streams in localStorage

---

## 6. Payment & Subscription

### 6.1 Juspay Integration
- [ ] 🔴 Payment initiation creates Juspay order
- [ ] 🔴 Correct return URL is configured (not localhost)
- [ ] 🔴 Payment gateway loads correctly (not stuck on HDFC page)
- [ ] 🔴 UAT vs Production environment is configured correctly
- [ ] 🔴 Payment success callback is received
- [ ] 🔴 Payment failure callback is handled

### 6.2 Payment Page
- [ ] 🔴 `/payment` route exists and renders
- [ ] 🔴 Payment page has different theme (not home page background/navbar)
- [ ] 🔴 Payment page uses onboarding gradient theme
- [ ] 🔴 Failed payment shows error message
- [ ] 🔴 Successful payment redirects to agent new chat

### 6.3 Subscription Management
- [ ] 🔴 Subscription is created on payment success
- [ ] 🔴 Subscription status is queryable
- [ ] 🔴 Plan entitlements are checked correctly
- [ ] 🔴 Expired subscriptions are handled
- [ ] 🔴 499 plan grants research agent access

### 6.4 Plan Catalog
- [ ] 🔴 Plans are loaded from database/config
- [ ] 🔴 Plan features are displayed correctly
- [ ] 🔴 Plan pricing is accurate

---

## 7. Admin Features

### 7.1 Admin Access
- [ ] 🔴 Admin pages require admin JWT flag
- [ ] 🔴 Super admin pages require super JWT flag
- [ ] 🔴 Phone numbers in admin list grant admin access

### 7.2 Admin Users Management
- [ ] 🔴 User list displays correctly
- [ ] 🔴 User email and phone number are shown
- [ ] 🔴 "Not Set" shows for missing phone/email
- [ ] 🔴 Click on "Not Set" phone redirects to phone form
- [ ] 🔴 Phone verification with JWT updates user (not creates new)

### 7.3 Admin Subscription Grants
- [ ] 🔴 Admin can grant subscription to any user
- [ ] 🔴 Grant is logged with admin user ID
- [ ] 🔴 Team members can be unlocked via admin
- [ ] 🔴 Granted subscriptions work correctly

### 7.4 Admin Observability
- [ ] 🔴 Skill call logs are viewable
- [ ] 🔴 Skill call details page loads

### 7.5 Admin System Config
- [ ] 🔴 System config is viewable
- [ ] 🔴 Config changes are saved

### 7.6 Agent Management
- [ ] 🔴 Custom agents can be created
- [ ] 🔴 Custom agents can be deleted
- [ ] 🔴 Deleting agent handles null agent_id in conversations
- [ ] 🔴 Research-orchestrator agent is not affected by custom agent deletion

### 7.7 Background Tasks UI
- [ ] 🔴 Developer option for background tasks is movable by mouse drag
- [ ] 🔴 Drag functionality works correctly

---

## 8. API Security & Performance

### 8.1 Authentication
- [ ] 🔴 All protected endpoints validate JWT
- [ ] 🔴 JWT signature is verified
- [ ] 🔴 Expired JWT is rejected
- [ ] 🔴 Invalid JWT format is rejected

### 8.2 Authorization
- [ ] 🔴 User can only access own data
- [ ] 🔴 Admin endpoints check admin flag
- [ ] 🔴 Super admin endpoints check super flag

### 8.3 Input Validation
- [ ] 🔴 SQL injection is prevented
- [ ] 🔴 XSS is prevented
- [ ] 🔴 Invalid UUIDs are rejected
- [ ] 🔴 Required fields are validated

### 8.4 Rate Limiting
- [ ] 🔴 OTP endpoints are rate limited
- [ ] 🔴 AI chat endpoints have reasonable limits
- [ ] 🔴 Crawl endpoints are rate limited

### 8.5 CORS
- [ ] 🔴 CORS is configured for production domains
- [ ] 🔴 Localhost is not allowed in production

### 8.6 Error Handling
- [ ] 🔴 Errors don't leak sensitive information
- [ ] 🔴 Stack traces are not exposed in production
- [ ] 🔴 Consistent error response format

---

## 9. Frontend UI/UX

### 9.1 Navigation
- [ ] 🔴 Left navigation sidebar works
- [ ] 🔴 Products sidebar shows product list items:
  - Ecom Listing SEO (Improve 30-40% Revenue)
  - Learn from Competitors (Best Growth Hacks)
  - B2B Lead Gen (Reddit and LinkedIn Hot leads)
  - Youtube Helper (Script + Thumbnail + Keyword analysis)
  - AI Team Professionals (Marketing / Ops / HR etc)
  - Content Creator (SEO / Insta / Blogs / LinkedIn)
- [ ] 🔴 "Our Products" opens left navigation with above items
- [ ] 🔴 How It Works navbar button links to `/how-it-works`

### 9.2 How It Works Page
- [ ] 🔴 `/how-it-works` route exists
- [ ] 🔴 Page has same structure/content as static HTML design
- [ ] 🔴 Page uses onboarding gradient theme
- [ ] 🔴 Page is within frontend (not external)

### 9.3 Account Page
- [ ] 🔴 Plan information displays
- [ ] 🔴 Email information displays
- [ ] 🔴 Phone number displays (or "Not Set")
- [ ] 🔴 "Not Set" phone redirects to phone form
- [ ] 🔴 Google login updates existing user with JWT

### 9.4 Error Boundaries
- [ ] 🔴 ErrorBoundary catches React errors
- [ ] 🔴 Error fallback UI displays
- [ ] 🔴 Errors are logged

### 9.5 Responsive Design
- [ ] 🔴 Mobile layout works
- [ ] 🔴 Tablet layout works
- [ ] 🔴 Desktop layout works

### 9.6 Loading States
- [ ] 🔴 Loading indicators for async operations
- [ ] 🔴 Skeleton screens where appropriate

---

## 10. Database & Data Integrity

### 10.1 Migrations
- [ ] 🔴 All migrations run successfully
- [ ] 🔴 `playbook_result` column exists in onboarding table
- [ ] 🔴 `plan_runs_status_check` constraint includes 'interrupted'
- [ ] 🔴 OTP table exists for PostgreSQL OTP storage

### 10.2 Foreign Keys
- [ ] 🔴 Conversation agent_id allows NULL or has proper cascade
- [ ] 🔴 User references are consistent
- [ ] 🔴 Session references are consistent

### 10.3 Constraints
- [ ] 🔴 Required NOT NULL constraints are enforced
- [ ] 🔴 Status enums/checks are up to date
- [ ] 🔴 UUID format is validated

### 10.4 Data Consistency
- [ ] 🔴 Onboarding session cleanup doesn't orphan data
- [ ] 🔴 User deletion cascades appropriately
- [ ] 🔴 Conversation deletion handles related data

---

## 11. Error Handling & Recovery

### 11.1 Backend Restart Recovery
- [ ] 🔴 Running plan executions are detected on startup
- [ ] 🔴 Orphaned processes are marked as interrupted
- [ ] 🔴 Error message explains backend restart
- [ ] 🔴 Retry option is available

### 11.2 Network Errors
- [ ] 🔴 API timeouts are handled
- [ ] 🔴 Retry logic for transient failures
- [ ] 🔴 Offline state is detected

### 11.3 LLM API Errors
- [ ] 🔴 OpenRouter 401 errors show meaningful message
- [ ] 🔴 API key validation on startup
- [ ] 🔴 Fallback behavior for LLM failures
- [ ] 🔴 Final report generation failure is captured

### 11.4 Stream Errors
- [ ] 🔴 SSE connection drops are handled
- [ ] 🔴 Stream resume after reconnection
- [ ] 🔴 Permanent failures clean up state

---

## 12. External Integrations

### 12.1 OpenRouter
- [ ] 🔴 API key is configured correctly
- [ ] 🔴 `sk-or-v1-` prefix is valid
- [ ] 🔴 401 errors are debugged (check env vs settings)
- [ ] 🔴 Rate limits are handled

### 12.2 Google OAuth
- [ ] 🔴 Client ID/Secret configured
- [ ] 🔴 Redirect URIs configured for production
- [ ] 🔴 Scope permissions are correct

### 12.3 SMS/OTP Provider
- [ ] 🔴 SMS API is configured
- [ ] 🔴 OTP delivery works
- [ ] 🔴 Fallback for SMS failures

### 12.4 Juspay
- [ ] 🔴 Merchant ID configured
- [ ] 🔴 API key configured
- [ ] 🔴 Return URL is production URL
- [ ] 🔴 UAT vs Production environment switch

### 12.5 Website Crawler
- [ ] 🔴 Crawler service is accessible
- [ ] 🔴 Crawl results are parsed correctly
- [ ] 🔴 Crawl timeouts are handled

---

## 13. Deployment & Infrastructure

### 13.1 Environment Configuration
- [ ] 🔴 Production `.env` has correct values
- [ ] 🔴 No localhost URLs in production config
- [ ] 🔴 Secrets are not in code
- [ ] 🔴 DATABASE_URL points to production DB

### 13.2 Docker
- [ ] 🔴 Docker images build successfully
- [ ] 🔴 Docker compose works
- [ ] 🔴 Health checks are configured

### 13.3 Cloud Run / GCP
- [ ] 🔴 Service deploys successfully
- [ ] 🔴 Memory limits are adequate
- [ ] 🔴 Timeout settings are appropriate
- [ ] 🔴 Cold start is acceptable

### 13.4 Database
- [ ] 🔴 Production database is accessible
- [ ] 🔴 Connection pooling is configured
- [ ] 🔴 Migrations are applied

### 13.5 Monitoring
- [ ] 🔴 Logging is configured
- [ ] 🔴 Error tracking is enabled
- [ ] 🔴 Performance monitoring
- [ ] 🔴 Alerting for critical errors

### 13.6 SSL/TLS
- [ ] 🔴 HTTPS is enforced
- [ ] 🔴 Certificates are valid
- [ ] 🔴 HSTS is enabled

---

## Critical Bugs to Fix Before Production

Based on conversation history, these issues were identified:

### P0 - Blocking
1. [ ] 🔴 `insights is not defined` error in AssistantMessage component
2. [ ] 🔴 Plan execution not using task stream (still polling)
3. [ ] 🔴 Retry button not working for interrupted plans
4. [ ] 🔴 Fresh "Start Working" doesn't clear stale streams
5. [ ] 🔴 Agent deletion sets research-orchestrator ID to null
6. [ ] 🔴 `plan_runs_status_check` constraint missing 'interrupted'

### P1 - High Priority
1. [ ] 🔴 Onboarding state restoration not going to RCA stage
2. [ ] 🔴 Payment redirect URL pointing to localhost
3. [ ] 🔴 OTP stored in Redis (should be PostgreSQL)
4. [ ] 🔴 Phone verify redirecting back to home page
5. [ ] 🔴 `/payment` route returning 404

### P2 - Medium Priority
1. [ ] 🔴 Background tasks UI not draggable
2. [ ] 🔴 Arrow SVG scaling issues
3. [ ] 🔴 Diagnostic questions styling mismatch
4. [ ] 🔴 State API called in loop

---

## Sign-off

| Role | Name | Date | Status |
|------|------|------|--------|
| QA Lead | | | |
| Backend Lead | | | |
| Frontend Lead | | | |
| DevOps | | | |
| Product Owner | | | |

---

## Appendix: Test Environment Setup

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with test credentials
python -m uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
cp .env.example .env
# Edit .env with test API URL
npm run dev

# Database
docker-compose up -d postgres
alembic upgrade head
```

## Appendix: API Endpoints to Test

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/v1/auth/google` | POST | No | Google OAuth |
| `/api/v1/auth/otp/send` | POST | No | Send OTP |
| `/api/v1/auth/otp/verify` | POST | No | Verify OTP |
| `/api/v1/onboarding/state` | GET | Optional | Get onboarding state |
| `/api/v1/onboarding/upsert` | POST | Optional | Update onboarding |
| `/api/v1/ai-chat/conversations` | GET | Yes | List conversations |
| `/api/v1/ai-chat/messages` | POST | Yes | Send message |
| `/api/v1/ai-chat/agent-access` | GET | Yes | Check agent access |
| `/api/v1/task-stream/start/*` | POST | Yes | Start task stream |
| `/api/v1/task-stream/events/*` | GET | Yes | Stream events |
| `/api/v1/payments/create` | POST | Yes | Create payment |
| `/api/admin/*` | * | Admin | Admin endpoints |

