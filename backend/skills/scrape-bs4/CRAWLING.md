# Discovery & crawling (scrape-bs4)

## How it works

The BS4 skill already implements **discovery** and **crawling**:

1. **Seed URLs**
   - Start from the given `url`.
   - If present, fetch `sitemap.xml` / `sitemap_index.xml` / `sitemap.txt` and add up to 50 URLs from the same domain to the queue (depth 1).

2. **BFS crawl**
   - Visit each URL, parse HTML with BeautifulSoup.
   - Extract internal links (`<a href="...">`) and add them to the queue at `depth + 1`.
   - Stop when `max_pages` is reached or no more links, or when `max_depth` is exceeded.

3. **Respects**
   - `robots.txt` (optional, on by default).
   - Skips non-HTML (PDF, images, etc.) and duplicate URLs.

4. **Parameters** (from skill input or defaults)
   - `url` – root URL to crawl.
   - `maxPages` – cap on number of pages (default 30).
   - `maxDepth` – max link depth from seed (default 4).

## Why only 1 page for some sites?

Sites that render content with **JavaScript** (e.g. React/Vue SPAs) often serve minimal static HTML (“Loading…”, “Initializing…”). BeautifulSoup only sees that HTML, so:

- There is little or no `body_text`.
- There may be no (or few) `<a href>` links in the initial HTML.

For such sites, use **scrape-playwright** (headless browser) so the crawler sees the fully rendered DOM and can extract content and links after JS runs.

## Crawling tools in this repo

| Skill              | Tool         | Best for                    | Discovery                    |
|--------------------|-------------|-----------------------------|------------------------------|
| **scrape-bs4**     | requests + BeautifulSoup | Static HTML, fast, low resource | Sitemap + following `<a href>` |
| **scrape-playwright** | Playwright (headless browser) | JS-rendered sites        | Same idea, after JS execution  |

## Other tools you could add

- **Scrapy** – full crawl framework (sitemap, rules, middlewares).
- **Crawl4AI** – LLM-oriented crawler with optional Playwright.
- **Firecrawl** (API) – managed crawl + scrape.

For most static sites, the built-in **scrape-bs4** discovery (sitemap + BFS) is enough; for SPAs, use **scrape-playwright** once its Python environment is set up (venv + `playwright install`).
