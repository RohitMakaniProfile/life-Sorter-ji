# Website Scraping & Analysis Flow — Complete Documentation

> Everything that happens after a business URL is submitted in the Life Sorter app.

---

## Table of Contents

1. [Frontend URL Submission](#1-frontend-url-submission)
2. [Backend Endpoint](#2-backend-endpoint)
3. [Website Crawling — What Gets Scraped](#3-website-crawling--what-gets-scraped)
4. [Crawl Summary Generation (GPT)](#4-crawl-summary-generation-gpt)
5. [Background Crawl Execution](#5-background-crawl-execution)
6. [Website Audience Analysis (GPT)](#6-website-audience-analysis-gpt)
7. [Response to Frontend](#7-response-to-frontend)
8. [Data Persistence & Storage](#8-data-persistence--storage)
9. [RCA Integration — How Crawl Data Feeds the Agent](#9-rca-integration--how-crawl-data-feeds-the-agent)
10. [Google Sheets Export](#10-google-sheets-export)
11. [Error Handling & Resilience](#11-error-handling--resilience)
12. [Complete Data Flow Diagram](#12-complete-data-flow-diagram)

---

## 1. Frontend URL Submission

**File:** `frontend/src/components/ChatBotNew.jsx`

### How the user submits a URL:
- The user types or pastes a business URL into the chat interface.
- The frontend auto-prepends `https://` if no protocol is provided.
- The URL is validated (non-empty check).
- The URL is displayed in the chat as a user message.

### API call made:
```
POST /api/v1/agent/session/website
```

### Request payload:
```json
{
  "session_id": "<active-session-uuid>",
  "website_url": "https://example.com"
}
```

---

## 2. Backend Endpoint

**File:** `backend/app/routers/agent.py`

### Endpoint: `POST /api/v1/agent/session/website`

### Handler: `submit_website()`

### What it does:
1. Validates the session exists in the session store.
2. Stores the URL in the session via `session_store.set_website_url()`.
3. Kicks off a **background crawl** (fire-and-forget async task).
4. Triggers **website audience analysis** (awaited — blocks the response).
5. Returns audience insights + business summary to the frontend.

---

## 3. Website Crawling — What Gets Scraped

**File:** `backend/app/services/crawl_service.py`  
**Main function:** `crawl_website(website_url: str) -> dict`  
**HTTP library:** `httpx` (async)  
**User-Agent:** `Mozilla/5.0 (compatible; IkshanBot/2.0)`  
**Timeout:** 15 seconds per request  

### 3.1 Homepage Extraction

| Field | Description | Limit |
|-------|-------------|-------|
| `title` | Page `<title>` tag | Max 200 chars |
| `meta_desc` | `<meta name="description">` content | Max 500 chars |
| `h1s` | All `<h1>` headline texts | Up to 5 |
| `nav_links` | Internal navigation links (href + text) | Up to 30 |
| `has_viewport` | Whether `<meta name="viewport">` exists | Boolean |
| `has_meta` | Whether title + meta description are both present | Boolean |

### 3.2 Internal Pages Crawled

Up to **5 internal pages** are crawled from the homepage's navigation links.

**Pages targeted by type (regex-based path matching):**
- `/about` — About page
- `/pricing` — Pricing page
- `/products` or `/services` — Products/services page
- `/contact` — Contact page
- `/blog` — Blog page

**Extracted per page:**
- Page type (about, pricing, etc.)
- Key text content (max **1500 chars** per page)

**Concurrency:** All internal pages are fetched concurrently using `asyncio.gather()`.

### 3.3 Tech Stack Detection

**24 technologies** are detected from the HTML source:

| Category | Technologies Detected |
|----------|----------------------|
| **CMS / Website Builders** | WordPress, Shopify, Squarespace, Wix, Webflow |
| **JS Frameworks** | React, Vue, Angular, Gatsby |
| **Marketing & CRM** | HubSpot, Mailchimp, Intercom |
| **Support** | Zendesk, Calendly |
| **Analytics** | Google Analytics, Google Tag Manager, Hotjar, Facebook Pixel |
| **Payments** | Stripe |
| **CDN / Security** | Cloudflare |
| **CSS Frameworks** | Bootstrap, Tailwind CSS |

### 3.4 CTA (Call-to-Action) Patterns

- Extracts button text from `<button>` tags.
- Extracts link text from elements with CTA-related CSS classes.
- **Limit:** Up to 10 CTAs, max 50 chars each.

### 3.5 Social Media Links

Detected platforms:
- Instagram
- Facebook
- Twitter / X
- LinkedIn
- TikTok
- YouTube
- Pinterest
- Threads

**Limit:** Up to 10 unique social profile URLs.

### 3.6 Schema Markup (JSON-LD)

- Extracts `@type` values from `<script type="application/ld+json">` blocks.
- Examples: `Organization`, `LocalBusiness`, `Product`, `WebSite`, etc.
- **Limit:** Up to 10 schema types.

### 3.7 SEO Basics Check

| Check | What It Means |
|-------|---------------|
| `has_meta` | Both title and meta description are present |
| `has_viewport` | Mobile viewport meta tag exists |
| `has_sitemap` | Sitemap reference detected |

### Complete Raw Crawl Data Structure

```python
{
    "url": "https://example.com",
    "title": "Example Business - Home",
    "meta_desc": "We help businesses grow...",
    "h1s": ["Welcome to Example Business"],
    "nav_links": [
        {"href": "/about", "text": "About Us"},
        {"href": "/pricing", "text": "Pricing"},
        # ... up to 30
    ],
    "tech_stack": ["React", "Google Analytics", "Stripe"],
    "ctas": ["Get Started", "Book a Demo", "Sign Up Free"],
    "social_links": [
        "https://instagram.com/example",
        "https://linkedin.com/company/example"
    ],
    "schema_types": ["Organization", "WebSite"],
    "seo_basics": {
        "has_meta": true,
        "has_viewport": true,
        "has_sitemap": false
    },
    "pages": [
        {
            "type": "about",
            "url": "https://example.com/about",
            "content": "Founded in 2020, we are a team of..."
        },
        {
            "type": "pricing",
            "url": "https://example.com/pricing",
            "content": "Starter: $29/mo, Pro: $99/mo..."
        }
        # ... up to 5 pages
    ]
}
```

---

## 4. Crawl Summary Generation (GPT)

**File:** `backend/app/services/crawl_service.py`  
**Function:** `generate_crawl_summary(crawl_raw, website_url) -> dict`  
**Model:** OpenAI GPT-4o-mini  
**Temperature:** 0.3 (deterministic)  
**Max tokens:** 300  
**Response format:** JSON  

### What GPT receives as context:
- Homepage title and meta description
- H1 headlines
- Tech stack (first 8)
- CTAs (first 5)
- Number of social profiles
- SEO issues detected
- All crawled pages with type + content preview

### What GPT returns — 5 bullet-point summary:

| # | Bullet Point | Purpose |
|---|--------------|---------|
| 1 | What the business does | Core offering/service |
| 2 | Who they target | Target audience / market |
| 3 | Tech sophistication level | How advanced their digital presence is |
| 4 | Key strengths | What they're doing well |
| 5 | Notable gap or opportunity | Where they can improve |

### Fallback:
If GPT fails, a basic summary is generated from the raw crawl data programmatically.

---

## 5. Background Crawl Execution

**File:** `backend/app/services/crawl_service.py`  
**Function:** `run_background_crawl(session_id, website_url)`  
**Execution pattern:** Fire-and-forget async task (non-blocking)

### Steps:
1. Set `crawl_status` → `"in_progress"` in session.
2. Execute full `crawl_website()` extraction.
3. Generate crawl summary via GPT-4o-mini.
4. Store results in session:
   - `session.crawl_raw` — Full scraped data
   - `session.crawl_summary` — Compressed 5-point summary
   - `session.crawl_status` → `"complete"`
5. On failure: `crawl_status` → `"failed"`, error is logged.

> **Important:** This runs in the background. The API response to the user does NOT wait for this to finish. The audience analysis (Section 6) is what the user sees immediately.

---

## 6. Website Audience Analysis (GPT)

**File:** `backend/app/services/agent_service.py`  
**Function:** `analyze_website_audience(website_url, outcome_label, domain, task, rca_history) -> dict`

### Process:
1. Fetch website HTML using `httpx`.
2. **Clean the HTML:**
   - Remove all `<script>` and `<style>` blocks.
   - Strip all remaining HTML tags.
   - Collapse excessive whitespace.
   - Truncate to **5000 characters** max.
3. Send cleaned text to GPT for analysis.

### What GPT analyzes:
- **Intended audience** — Who the business is trying to reach
- **Actual audience** — Who the content/copy actually speaks to
- **Mismatch analysis** — Gap between intended vs actual with evidence
- **Recommendations** — 3 actionable fixes

### Output structure:
```json
{
    "intended_audience": "Small to medium B2B SaaS companies looking for...",
    "actual_audience": "The website copy primarily speaks to enterprise...",
    "mismatch_analysis": "While the pricing suggests SMB targeting, the language and case studies are enterprise-focused, creating confusion for...",
    "recommendations": [
        "Add SMB-specific case studies to the homepage",
        "Simplify the pricing page with a clear starter tier",
        "Include testimonials from companies of the target size"
    ],
    "business_summary": "Example Corp is a B2B analytics platform that..."
}
```

---

## 7. Response to Frontend

### API Response structure:
```json
{
    "session_id": "uuid-string",
    "website_url": "https://example.com",
    "audience_insights": {
        "intended_audience": "...",
        "actual_audience": "...",
        "mismatch_analysis": "...",
        "recommendations": ["...", "...", "..."]
    },
    "business_summary": "...",
    "analysis_note": "I've analyzed your website..."
}
```

### Frontend rendering:
- Business summary is displayed first.
- Intended vs actual audience comparison is shown in formatted markdown.
- Gap analysis with specific evidence.
- 3 quick-win recommendations are listed.

---

## 8. Data Persistence & Storage

### Session fields populated:

| Field | Type | Description |
|-------|------|-------------|
| `website_url` | string | The submitted URL |
| `url_submitted_at` | ISO timestamp | When the URL was submitted |
| `url_type` | string | `"website"` or `"social_profile"` |
| `audience_insights` | dict | Full audience analysis from GPT |
| `crawl_raw` | dict | Complete raw scraped data (async) |
| `crawl_summary` | dict | 5-point GPT summary (async) |
| `crawl_status` | string | `"in_progress"` / `"complete"` / `"failed"` |

### Database: **Supabase**

**File:** `backend/app/services/supabase_service.py`

#### Tables used:
| Table | What's Stored |
|-------|--------------|
| `conversations` | Session messages + recommendations history |
| `leads` | User info if they complete the flow (name, email, domain, website, etc.) |

---

## 9. RCA Integration — How Crawl Data Feeds the Agent

**File:** `backend/app/services/claude_rca_service.py`  
**LLM:** Anthropic Claude Sonnet 4 (via OpenRouter)  
**API:** `https://openrouter.ai/api/v1/chat/completions`

### How scraped data enhances the RCA conversation:

| Crawl Data Used | How It's Used in RCA |
|----------------|---------------------|
| Crawl summary | Provides business context for Claude's first diagnostic question |
| Website insights | Informs business profile calibration |
| Tech stack signals | Drives questions about current tools and integrations |
| SEO issues found | Triggers follow-up questions about visibility problems |
| CTA patterns | Used to assess conversion optimization maturity |
| Page content | Cross-referenced with user's RCA answers for precision questions |

The crawl data essentially gives Claude context about the business **before** it starts asking diagnostic questions, so it can ask smarter, more targeted questions.

---

## 10. Google Sheets Export

**File:** `backend/app/services/sheets_service.py`

### Company recommendation sheets:
- **Consolidated sheet ID:** `1d6nrGP4yRbx_ddzClAheicsavF2OsmINJmMDIQIL4m0`
- **9 domain-specific sheets:** Marketing, Sales, Legal, HR, Finance, etc.

### AI-Powered company matching:
- GPT matches user requirements to startups in the sheets.
- Scoring on a **0–10 scale** based on problem/solution fit.
- Returns **top 3 matches** + alternatives.

---

## 11. Error Handling & Resilience

### Crawl-level errors:
- HTTP timeout: 15 seconds per request, fails gracefully.
- Invalid URLs: Caught and logged.
- Background crawl failure sets `crawl_status = "failed"` — never throws to API caller.

### Audience analysis fallback:
```python
# If GPT analysis fails entirely:
{
    "intended_audience": "",
    "actual_audience": "",
    "mismatch_analysis": "We couldn't fully analyze this website...",
    "recommendations": [],
    "business_summary": ""
}
```

### Rate limiting:
- **10 requests/minute** on chat endpoints (applies to website submission).

### Logging:
- Structured logging via `structlog`.
- Tracked: session ID, URL, success/failure, duration, error messages.

---

## 12. Complete Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                │
│  User pastes URL → auto-prepend https:// → validate → POST     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
                 POST /api/v1/agent/session/website
                   { session_id, website_url }
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND (agent.py)                            │
│                                                                 │
│  1. Validate session                                            │
│  2. Store URL in session                                        │
│  3. Launch background crawl ──────────────────┐                 │
│  4. Await audience analysis                   │                 │
│  5. Return response to frontend               │                 │
└───────────────┬───────────────────────────────┼─────────────────┘
                │                               │
    ┌───────────▼──────────┐      ┌─────────────▼──────────────┐
    │  AUDIENCE ANALYSIS   │      │    BACKGROUND CRAWL        │
    │  (agent_service.py)  │      │    (crawl_service.py)      │
    │                      │      │                            │
    │  • Fetch HTML        │      │  • Fetch homepage HTML     │
    │  • Strip tags        │      │  • Extract title, meta,    │
    │  • Truncate 5K chars │      │    h1s, nav links          │
    │  • GPT analysis:     │      │  • Detect 24 tech stacks   │
    │    - Intended aud.   │      │  • Extract CTAs            │
    │    - Actual aud.     │      │  • Find social links       │
    │    - Mismatch gap    │      │  • Parse schema markup     │
    │    - 3 recs          │      │  • Check SEO basics        │
    │    - Biz summary     │      │  • Crawl 5 internal pages  │
    └───────────┬──────────┘      │  • GPT summary (5 points)  │
                │                 └─────────────┬──────────────┘
                │                               │
                ▼                               ▼
    ┌──────────────────┐          ┌──────────────────────────┐
    │  API RESPONSE    │          │  SESSION STORE UPDATE    │
    │  (immediate)     │          │  (async, non-blocking)   │
    │                  │          │                          │
    │  audience_insights│         │  crawl_raw               │
    │  business_summary │         │  crawl_summary           │
    │  analysis_note    │         │  crawl_status: complete  │
    └────────┬─────────┘          └────────────┬─────────────┘
             │                                 │
             ▼                                 ▼
    ┌──────────────────┐          ┌──────────────────────────┐
    │  FRONTEND RENDER │          │  USED LATER IN RCA       │
    │  • Biz summary   │          │  (claude_rca_service.py)  │
    │  • Audience comp  │          │                          │
    │  • Gap analysis   │          │  Crawl data provides     │
    │  • 3 quick wins   │          │  context for Claude's    │
    └──────────────────┘          │  diagnostic questions    │
                                  └──────────────────────────┘
                                              │
                                              ▼
                                  ┌──────────────────────────┐
                                  │  SUPABASE (persistence)  │
                                  │  • conversations table   │
                                  │  • leads table           │
                                  └──────────────────────────┘
```

---

## Summary — What You Scrape (Quick Reference)

| Category | Data Points |
|----------|-------------|
| **Basic SEO** | Title, meta description, H1s, viewport, sitemap |
| **Navigation** | Up to 30 internal links (href + text) |
| **Tech Stack** | 24 technologies (CMS, frameworks, analytics, payment, etc.) |
| **CTAs** | Up to 10 call-to-action button/link texts |
| **Social Links** | 8 platforms (Instagram, FB, X, LinkedIn, TikTok, YT, Pinterest, Threads) |
| **Schema** | JSON-LD types (Organization, Product, etc.) |
| **Internal Pages** | Up to 5 pages (about, pricing, products, contact, blog) — 1500 chars each |
| **Audience Analysis** | Intended vs actual audience, gap analysis, 3 recommendations |
| **Business Summary** | 5-bullet GPT summary of what the business does |
