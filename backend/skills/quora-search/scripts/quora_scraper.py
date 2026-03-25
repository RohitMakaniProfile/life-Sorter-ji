#!/usr/bin/env python3
"""
biz-scrape-quora: Fetch questions, answers, and discussions about a business or topic
from Quora.

Extracts top questions, highest-voted answers, author credentials, themes, and
competitor mentions. Uses direct HTTP + Google cache/search fallback for blocked pages.

Usage:
    python3 quora_scraper.py --target "Is Notion worth it" --output quora.json
    python3 quora_scraper.py --target "https://www.quora.com/Is-Notion-worth-using" --output quora.json
"""

import argparse
import hashlib
import json
import os
import re
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[quora] ERROR: Missing deps. Run: pip3 install requests beautifulsoup4")
    raise SystemExit(1)


HEADERS_DIRECT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Googlebot can sometimes get Quora's server-rendered content
HEADERS_GOOGLEBOT = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html",
}


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(target: str) -> dict:
    """Determine target type from input."""
    target = target.strip()

    # Direct Quora question URL
    if "quora.com/" in target:
        return {"type": "url", "value": target}

    # Assume search query
    return {"type": "search", "value": target}


def build_quora_search_url(query: str) -> str:
    encoded = urllib.parse.quote_plus(query)
    return f"https://www.quora.com/search?q={encoded}"


def build_google_search_url(query: str) -> str:
    encoded = urllib.parse.quote_plus(f"site:quora.com {query}")
    return f"https://www.google.com/search?q={encoded}&num=15&hl=en"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_page(url: str, headers=None, max_retries=3) -> str | None:
    """Fetch a page with retries and header rotation."""
    session = requests.Session()
    header_sets = [headers or HEADERS_DIRECT, HEADERS_GOOGLEBOT, HEADERS_DIRECT]
    for attempt in range(max_retries):
        try:
            h = header_sets[attempt % len(header_sets)]
            resp = session.get(url, headers=h, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 429):
                print(f"[quora] Blocked/rate-limited (HTTP {resp.status_code}), retrying...")
                time.sleep(2 * (attempt + 1))
                continue
            print(f"[quora] HTTP {resp.status_code} for {url[:80]}")
        except requests.RequestException as e:
            print(f"[quora] Fetch error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Quora page parsing
# ---------------------------------------------------------------------------

def extract_answers_from_question_page(html: str) -> list[dict]:
    """Extract answers from a Quora question page HTML."""
    answers = []
    soup = BeautifulSoup(html, "html.parser")

    # Quora renders answers in divs with specific class patterns
    # Try multiple selectors as Quora changes frequently
    answer_containers = (
        soup.find_all("div", class_=re.compile(r"Answer|AnswerBase|q-box"))
        or soup.find_all("div", {"data-testid": re.compile(r"answer")})
        or soup.find_all("div", class_=re.compile(r"spacing_log_answer"))
    )

    for container in answer_containers:
        answer = _parse_answer_container(container)
        if answer and answer["text"] and len(answer["text"]) > 20:
            # Dedupe
            prefix = answer["text"][:60]
            if not any(a["text"][:60] == prefix for a in answers):
                answers.append(answer)

    # If HTML parsing failed, try extracting from embedded JSON
    if not answers:
        answers = _extract_answers_from_json(html)

    return answers


def _parse_answer_container(container) -> dict | None:
    """Parse a single answer container element."""
    # Text content
    text_div = container.find("div", class_=re.compile(r"AnswerContent|FormattedText"))
    if not text_div:
        # Broader search
        paragraphs = container.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs)
    else:
        text = text_div.get_text(strip=True)

    if not text or len(text) < 20:
        return None

    # Author
    author = "Anonymous"
    author_link = container.find("a", class_=re.compile(r"user|author"))
    if author_link:
        author = author_link.get_text(strip=True) or "Anonymous"
    if not author_link:
        # Try spans with profile info
        spans = container.find_all("span")
        for s in spans:
            t = s.get_text(strip=True)
            if 2 < len(t) < 50 and not any(w in t.lower() for w in ["answer", "view", "upvote", "share", "follow"]):
                author = t
                break

    # Credentials
    credentials = None
    cred_el = container.find("span", class_=re.compile(r"credential|bio"))
    if cred_el:
        credentials = cred_el.get_text(strip=True)
    if not credentials:
        # Look for text like "Author at Company" or "X years experience"
        for span in container.find_all("span"):
            t = span.get_text(strip=True)
            if any(w in t.lower() for w in [" at ", " of ", "years", "engineer", "manager", "founder", "ceo", "developer"]):
                if 5 < len(t) < 100:
                    credentials = t
                    break

    # Upvotes
    upvotes = None
    upvote_el = container.find(string=re.compile(r"\d+\s*(?:upvotes?|K)"))
    if upvote_el:
        m = re.search(r"([\d.]+)\s*K?\s*upvotes?", str(upvote_el), re.I)
        if m:
            val = float(m.group(1))
            if "K" in str(upvote_el):
                val *= 1000
            upvotes = int(val)

    return {
        "author": author,
        "author_credentials": credentials,
        "text": text[:3000],
        "upvotes": upvotes,
        "is_top_answer": False,
        "date": None,
    }


def _extract_answers_from_json(html: str) -> list[dict]:
    """Try to extract answers from Quora's embedded JSON data."""
    answers = []

    # Quora sometimes embeds data in script tags
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>([\s\S]*?)</script>', html):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, dict):
                # QAPage schema
                accepted = data.get("acceptedAnswer") or data.get("suggestedAnswer", [])
                if not isinstance(accepted, list):
                    accepted = [accepted]
                for ans in accepted:
                    text = ans.get("text", "")
                    if len(text) > 20:
                        answers.append({
                            "author": ans.get("author", {}).get("name", "Anonymous"),
                            "author_credentials": None,
                            "text": text[:3000],
                            "upvotes": ans.get("upvoteCount"),
                            "is_top_answer": ans == data.get("acceptedAnswer"),
                            "date": ans.get("dateCreated"),
                        })
        except (json.JSONDecodeError, AttributeError):
            pass

    return answers


def extract_question_metadata(html: str, url: str) -> dict:
    """Extract question title, followers, answer count from page."""
    soup = BeautifulSoup(html, "html.parser")
    meta = {"url": url}

    # Title
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "").replace(" - Quora", "").strip()
    meta["title"] = title or url.split("/")[-1].replace("-", " ")

    # Followers
    follow_match = re.search(r"([\d,]+)\s*(?:followers?|following)", html, re.I)
    if follow_match:
        meta["followers"] = int(follow_match.group(1).replace(",", ""))

    # Answer count
    ans_match = re.search(r"([\d,]+)\s*answers?", html, re.I)
    if ans_match:
        meta["answer_count"] = int(ans_match.group(1).replace(",", ""))

    return meta


# ---------------------------------------------------------------------------
# Google search for Quora questions
# ---------------------------------------------------------------------------

def find_quora_questions_via_google(query: str, max_questions: int) -> list[dict]:
    """Search Google for Quora question URLs related to the query."""
    url = build_google_search_url(query)
    print(f"[quora] Searching Google for Quora questions...")
    html = fetch_page(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    questions = []
    seen_urls = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Extract Quora URLs from Google results
        m = re.search(r"(https?://(?:www\.)?quora\.com/[A-Za-z0-9_-]+(?:\?[^&]*)?)", href)
        if not m:
            # Google wraps URLs in /url?q= redirects
            m = re.search(r"/url\?q=(https?://(?:www\.)?quora\.com/[^&]+)", href)
        if m:
            quora_url = urllib.parse.unquote(m.group(1)).split("&")[0]
            # Skip profile/topic/search pages
            if any(skip in quora_url for skip in ["/profile/", "/topic/", "/search?"]):
                continue
            if quora_url not in seen_urls:
                seen_urls.add(quora_url)
                # Extract title from link text or snippet
                title = a.get_text(strip=True).replace(" - Quora", "").strip()
                questions.append({"url": quora_url, "title": title or quora_url.split("/")[-1].replace("-", " ")})
                if len(questions) >= max_questions:
                    break

    return questions


def find_quora_questions_direct(query: str, max_questions: int) -> list[dict]:
    """Try searching Quora directly."""
    url = build_quora_search_url(query)
    html = fetch_page(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    questions = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/") and not any(skip in href for skip in ["/profile/", "/topic/", "/search", "/answer/"]):
            full_url = f"https://www.quora.com{href}"
            if full_url not in seen and len(href) > 5:
                seen.add(full_url)
                title = a.get_text(strip=True) or href.strip("/").replace("-", " ")
                questions.append({"url": full_url, "title": title})
                if len(questions) >= max_questions:
                    break

    return questions


# ---------------------------------------------------------------------------
# Theme & competitor extraction
# ---------------------------------------------------------------------------

POSITIVE_WORDS = {
    "love", "great", "amazing", "awesome", "excellent", "best", "perfect",
    "fantastic", "wonderful", "good", "recommend", "helpful", "useful",
    "powerful", "innovative", "intuitive", "reliable", "efficient",
}

NEGATIVE_WORDS = {
    "hate", "terrible", "awful", "worst", "bad", "horrible", "poor",
    "disappointing", "broken", "slow", "crash", "expensive", "overpriced",
    "confusing", "frustrating", "useless", "annoying", "complicated",
    "buggy", "lacking", "mediocre", "clunky", "steep learning curve",
}


def extract_themes(answers: list[dict]) -> dict:
    """Extract positive/negative/neutral themes from answer texts."""
    positive = Counter()
    negative = Counter()
    neutral = Counter()

    theme_keywords = {
        "pricing": ["price", "cost", "expensive", "cheap", "free", "paid", "subscription", "tier"],
        "performance": ["fast", "slow", "lag", "speed", "performance", "responsive"],
        "user experience": ["easy", "intuitive", "ui", "ux", "interface", "design", "clean"],
        "features": ["feature", "functionality", "capability", "tool", "integration"],
        "customer support": ["support", "help", "response", "service", "team"],
        "reliability": ["reliable", "stable", "crash", "bug", "downtime", "uptime"],
        "learning curve": ["learn", "onboarding", "tutorial", "documentation", "complex"],
        "value": ["worth", "value", "roi", "investment", "bang for buck"],
        "alternatives": ["alternative", "instead", "switch", "migrate", "replace", "competitor"],
        "security": ["security", "privacy", "data", "encryption", "safe"],
        "collaboration": ["team", "collaborate", "share", "workspace", "together"],
        "customization": ["custom", "flexible", "configurable", "template", "workflow"],
    }

    all_text = " ".join(a["text"].lower() for a in answers)
    words = set(re.findall(r"[a-z']+", all_text))

    for theme, keywords in theme_keywords.items():
        hits = sum(1 for kw in keywords if kw in all_text)
        if hits == 0:
            continue

        # Determine sentiment of this theme
        pos_near = sum(1 for w in words if w in POSITIVE_WORDS)
        neg_near = sum(1 for w in words if w in NEGATIVE_WORDS)

        if pos_near > neg_near * 1.5:
            positive[theme] = hits
        elif neg_near > pos_near * 1.5:
            negative[theme] = hits
        else:
            neutral[theme] = hits

    return {
        "positive": [t for t, _ in positive.most_common(5)],
        "negative": [t for t, _ in negative.most_common(5)],
        "neutral": [t for t, _ in neutral.most_common(5)],
    }


def extract_competitor_mentions(answers: list[dict], query: str) -> list[str]:
    """Find other products/services mentioned across answers."""
    # Common product/service name patterns
    all_text = " ".join(a["text"] for a in answers)

    # Look for capitalized product names and "X vs Y" patterns
    potential = set()

    # "vs" pattern
    for m in re.finditer(r"(\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+vs\.?\s+", all_text):
        potential.add(m.group(1).strip())
    for m in re.finditer(r"\s+vs\.?\s+(\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)", all_text):
        potential.add(m.group(1).strip())

    # "instead of X" / "switch to X" / "moved to X"
    for m in re.finditer(r"(?:instead of|switch(?:ed)? to|moved? to|try|use)\s+(\b[A-Z][a-zA-Z]+)", all_text, re.I):
        potential.add(m.group(1).strip())

    # Filter out common English words and the query subject itself
    query_words = set(query.lower().split())
    noise = {"the", "this", "that", "what", "which", "when", "where", "how", "why",
             "does", "not", "but", "for", "and", "with", "you", "your", "they",
             "have", "has", "had", "are", "was", "were", "been", "being", "very",
             "much", "more", "most", "some", "any", "all", "each", "every",
             "I", "We", "My", "Yes", "No", "It", "If", "So", "Also", "Just",
             "However", "Although", "Because", "While", "Though", "Here", "There"}

    competitors = []
    for name in potential:
        if name.lower() in query_words:
            continue
        if name in noise:
            continue
        if len(name) < 2 or len(name) > 30:
            continue
        competitors.append(name)

    return list(set(competitors))[:10]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Quora deep analysis scraper")
    parser.add_argument("--target", required=True, help="Search query or Quora URL")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--max-questions", type=int, default=10, help="Max questions (max 20)")
    parser.add_argument("--max-answers", type=int, default=5, help="Max answers per question (max 10)")
    args = parser.parse_args()

    max_questions = min(args.max_questions, 20)
    max_answers = min(args.max_answers, 10)
    resolved = resolve_target(args.target)

    print(f"[quora] Target: {resolved['type']} = {resolved['value'][:80]}")

    questions_to_scrape = []

    if resolved["type"] == "url":
        questions_to_scrape.append({
            "url": resolved["value"],
            "title": resolved["value"].split("/")[-1].replace("-", " "),
        })
        # Also search for related questions
        query = resolved["value"].split("/")[-1].replace("-", " ")
        if max_questions > 1:
            related = find_quora_questions_via_google(query, max_questions - 1)
            for r in related:
                if r["url"] != resolved["value"]:
                    questions_to_scrape.append(r)
    else:
        # Search for questions
        print("[quora] Finding relevant questions...")
        questions_to_scrape = find_quora_questions_via_google(resolved["value"], max_questions)
        if len(questions_to_scrape) < max_questions:
            direct = find_quora_questions_direct(resolved["value"], max_questions - len(questions_to_scrape))
            seen_urls = {q["url"] for q in questions_to_scrape}
            for q in direct:
                if q["url"] not in seen_urls:
                    questions_to_scrape.append(q)
                    seen_urls.add(q["url"])

    questions_to_scrape = questions_to_scrape[:max_questions]
    print(f"[quora] Found {len(questions_to_scrape)} question(s) to scrape.")

    all_questions = []
    all_answers_flat = []

    for i, q_info in enumerate(questions_to_scrape):
        print(f"[quora] Scraping question {i+1}/{len(questions_to_scrape)}: {q_info['title'][:60]}...")
        html = fetch_page(q_info["url"])

        if not html:
            all_questions.append({
                "title": q_info["title"],
                "url": q_info["url"],
                "followers": None,
                "answer_count": None,
                "answers": [],
            })
            continue

        meta = extract_question_metadata(html, q_info["url"])
        answers = extract_answers_from_question_page(html)

        # Mark first answer as top answer
        if answers:
            answers[0]["is_top_answer"] = True

        answers = answers[:max_answers]

        all_questions.append({
            "title": meta.get("title", q_info["title"]),
            "url": q_info["url"],
            "followers": meta.get("followers"),
            "answer_count": meta.get("answer_count"),
            "answers": answers,
        })
        all_answers_flat.extend(answers)

        if i < len(questions_to_scrape) - 1:
            time.sleep(1.5)

    total_answers = sum(len(q["answers"]) for q in all_questions)

    # Extract themes and competitor mentions
    themes = extract_themes(all_answers_flat) if all_answers_flat else {"positive": [], "negative": [], "neutral": []}
    competitors = extract_competitor_mentions(all_answers_flat, resolved["value"]) if all_answers_flat else []

    note = None
    if total_answers == 0:
        note = (
            "No answers could be extracted. Quora aggressively blocks scrapers and requires "
            "JavaScript rendering. Try combining with a headless browser skill for JS-heavy pages."
        )

    result = {
        "platform": "quora",
        "query": resolved["value"],
        "questions_scraped": len(all_questions),
        "total_answers": total_answers,
        "questions": all_questions,
        "themes": themes,
        "competitor_mentions": competitors,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"[quora] Done: {len(all_questions)} questions, {total_answers} answers, "
          f"{len(competitors)} competitor mentions -> {args.output}")


if __name__ == "__main__":
    main()

