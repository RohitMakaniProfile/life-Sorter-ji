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
  - Response: `text/event-stream` (SSE)
    - Streams JSON events matching the existing `scrape-playwright` progress schema
    - Ends with `{ "event": "done", "result": { "text": "...", "data": { ... } } }`

