"""URL priority scoring to guide crawl order, and subdomain filtering."""

import urllib.parse

HIGH_PRIORITY_KEYWORDS = [
    "about",
    "pricing", "price", "plans",
    "contact", "contact-us",
    "careers", "jobs", "hiring",
    "team", "company",
    "features", "product",
    "services",
    "faq", "help",
    "enterprise",
    "demo",
    "signup", "sign-up", "register",
    "privacy", "terms",
]

LOW_PRIORITY_KEYWORDS = [
    "docs", "documentation", "api-reference",
    "tutorial", "tutorials", "guide", "guides",
    "blog", "news", "updates",
    "changelog", "release-notes",
    "community", "forum", "support",
    "legal", "compliance",
]

SKIP_SUBDOMAINS = [
    "docs.", "app.", "api.", "status.", "community.",
    "forum.", "help.", "blog.", "support.",
    "cdn.", "static.", "assets.", "media.",
]


def _is_subdomain_url(url: str, base_domain: str) -> bool:
    """True if the URL is from a subdomain listed in SKIP_SUBDOMAINS."""
    parsed = urllib.parse.urlparse(url.lower())
    netloc = parsed.netloc
    if netloc == base_domain.lower():
        return False
    if netloc.endswith("." + base_domain.lower()):
        subdomain_prefix = netloc[: -(len(base_domain) + 1)]
        for skip_sub in SKIP_SUBDOMAINS:
            skip_prefix = skip_sub.rstrip(".")
            if subdomain_prefix == skip_prefix or subdomain_prefix.endswith("." + skip_prefix):
                return True
    return False


def _get_url_priority(url: str) -> int:
    """
    Score a URL so the crawler visits important pages first.
    100+ = homepage, 50–99 = high-value business pages, 10–49 = normal, 0–9 = low.
    """
    url_lower = url.lower()
    path = urllib.parse.urlparse(url_lower).path.strip("/")

    if not path:
        return 100

    for keyword in HIGH_PRIORITY_KEYWORDS:
        if keyword in path:
            depth = path.count("/")
            return max(50, 80 - depth * 10)

    for keyword in LOW_PRIORITY_KEYWORDS:
        if keyword in path:
            return 5

    depth = path.count("/")
    return max(10, 40 - depth * 5)