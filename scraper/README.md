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

