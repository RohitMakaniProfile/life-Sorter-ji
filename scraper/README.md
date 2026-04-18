## Playwright Scraper Microservice

Dedicated service to run the CPU-intensive Playwright crawl outside the backend container.

### API

- `POST /v1/scrape-playwright/stream`
  - Request JSON:
    - `url` (string, required)
    - `maxPages` (number, optional)
    - `maxDepth` (number, optional)
    - `deep` (boolean, optional)
    - `parallel` (boolean, optional)
    - `skipUrls` (string[], optional) — normalized URLs that already have `page_data` elsewhere; crawl skips a network fetch for them when still in the frontier
    - `resumeCheckpoint` (object, optional) — v1 parallel checkpoint `{ "v": 1, "parallel": true, "to_visit", "discovered", "scraped", "scraped_urls", "failed_urls", ... }` to continue mid-crawl (`parallel: true` only)
  - Response: `text/event-stream` (SSE)
    - Streams JSON events matching the existing `scrape-playwright` progress schema, including `{ "event": "checkpoint", "payload": { ... } }` after progress
    - Ends with `{ "event": "done", "result": { "text": "...", "data": { ... } } }`

**Resume:** Sequential (`parallel: false`) crawls do not support checkpoint restore yet. Use `parallel: true` for resumable runs.

### Code Structure

The `app/` directory is split into single-responsibility modules:

| File | Lines | Responsibility |
|------|-------|---------------|
| `playwright_scraper.py` | 79 | CLI entry point — parses args, calls crawler, writes result to stdout |
| `crawler.py` | 458 | Crawl orchestration: parallel async crawl (discovery + N scraper coroutines), resume from checkpoint, sequential BFS fallback |
| `main.py` | 254 | FastAPI HTTP server — receives `/v1/scrape-playwright/stream`, spawns scraper subprocess, streams SSE |
| `page_scraper.py` | 118 | Single-page scraping via async Playwright — returns a structured page record |
| `url_utils.py` | 110 | URL filtering, normalisation, link parsing, sitemap discovery |
| `html_extractor.py` | 95 | HTML text extraction and DOM element parsing (JS eval + regex fallback) |
| `url_priority.py` | 71 | URL scoring to guide crawl order (high-value pages first), subdomain filtering |
| `ocr_helper.py` | 136 | Google Vision API OCR — screenshots page and extracts text |
| `progress.py` | 16 | Thread-safe stderr JSON emitter used by all modules |

**Import chain:** `playwright_scraper` → `crawler` → `page_scraper` → `html_extractor`, `url_utils`; `crawler` also imports `url_utils`, `url_priority`, `progress`.

