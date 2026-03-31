"""
═══════════════════════════════════════════════════════════════
CHROME EXTENSIONS DATA — Extracted from ChatBotNew.jsx
═══════════════════════════════════════════════════════════════
Chrome extensions and plugins mapped to problem categories.
Used by the recommendations router.
"""

from __future__ import annotations

CHROME_EXTENSIONS_DATA: dict[str, list[dict]] = {
    "social-media": [
        {"name": "Buffer", "url": "https://chrome.google.com/webstore/detail/buffer", "description": "Schedule posts across all social platforms", "free": True},
        {"name": "Hootsuite", "url": "https://chrome.google.com/webstore/detail/hootsuite", "description": "Social media management dashboard", "free": False},
        {"name": "Canva", "url": "https://chrome.google.com/webstore/detail/canva", "description": "Create stunning social graphics instantly", "free": True},
    ],
    "seo-leads": [
        {"name": "SEOquake", "url": "https://chrome.google.com/webstore/detail/seoquake", "description": "Instant SEO metrics for any page", "free": True},
        {"name": "Keywords Everywhere", "url": "https://chrome.google.com/webstore/detail/keywords-everywhere", "description": "See search volume on Google", "free": False},
        {"name": "Hunter.io", "url": "https://chrome.google.com/webstore/detail/hunter", "description": "Find email addresses from any website", "free": True},
        {"name": "Ubersuggest", "url": "https://chrome.google.com/webstore/detail/ubersuggest", "description": "SEO insights and keyword ideas", "free": True},
    ],
    "ads-marketing": [
        {"name": "Facebook Pixel Helper", "url": "https://chrome.google.com/webstore/detail/facebook-pixel-helper", "description": "Debug your Facebook pixel", "free": True},
        {"name": "Google Tag Assistant", "url": "https://chrome.google.com/webstore/detail/tag-assistant", "description": "Verify Google tags are working", "free": True},
        {"name": "Adblock (for competitor research)", "url": "https://chrome.google.com/webstore/detail/adblock", "description": "See ads competitors are running", "free": True},
    ],
    "automation": [
        {"name": "Bardeen", "url": "https://chrome.google.com/webstore/detail/bardeen", "description": "Automate any repetitive browser task", "free": True},
        {"name": "Zapier", "url": "https://chrome.google.com/webstore/detail/zapier", "description": "Connect apps and automate workflows", "free": True},
        {"name": "Data Scraper", "url": "https://chrome.google.com/webstore/detail/data-scraper", "description": "Extract data from web pages", "free": True},
    ],
    "productivity": [
        {"name": "Notion Web Clipper", "url": "https://chrome.google.com/webstore/detail/notion-web-clipper", "description": "Save anything to Notion", "free": True},
        {"name": "Loom", "url": "https://chrome.google.com/webstore/detail/loom", "description": "Record quick video messages", "free": True},
        {"name": "Grammarly", "url": "https://chrome.google.com/webstore/detail/grammarly", "description": "Write better emails and docs", "free": True},
        {"name": "Otter.ai", "url": "https://chrome.google.com/webstore/detail/otter", "description": "AI meeting notes & transcription", "free": True},
    ],
    "research": [
        {"name": "Similar Web", "url": "https://chrome.google.com/webstore/detail/similarweb", "description": "Website traffic insights", "free": True},
        {"name": "Wappalyzer", "url": "https://chrome.google.com/webstore/detail/wappalyzer", "description": "See what tech websites use", "free": True},
        {"name": "ChatGPT for Google", "url": "https://chrome.google.com/webstore/detail/chatgpt-for-google", "description": "AI answers alongside search", "free": True},
    ],
    "finance": [
        {"name": "DocuSign", "url": "https://chrome.google.com/webstore/detail/docusign", "description": "E-sign documents from browser", "free": False},
        {"name": "Expensify", "url": "https://chrome.google.com/webstore/detail/expensify", "description": "Capture receipts instantly", "free": True},
    ],
    "support": [
        {"name": "Intercom", "url": "https://chrome.google.com/webstore/detail/intercom", "description": "Customer messaging platform", "free": False},
        {"name": "Zendesk", "url": "https://chrome.google.com/webstore/detail/zendesk", "description": "Support ticket management", "free": False},
        {"name": "Tidio", "url": "https://chrome.google.com/webstore/detail/tidio", "description": "Live chat + AI chatbot", "free": True},
    ],
}


# ── Category Matching Logic ────────────────────────────────────


# Maps keyword fragments → extension category keys
_CATEGORY_KEYWORDS = {
    "social-media": ["social", "content", "post"],
    "seo-leads": ["seo", "lead", "google"],
    "ads-marketing": ["ad", "marketing", "roi"],
    "automation": ["automate", "workflow"],
    "productivity": ["meeting", "email", "draft"],
    "research": ["competitor", "research", "trend"],
    "finance": ["finance", "invoice", "expense"],
    "support": ["support", "ticket", "chat"],
}

# Goal → category overrides
_GOAL_KEYWORDS = {
    "automation": ["save-time"],
}


def get_relevant_extensions(
    category: str = "",
    goal: str = "",
    limit: int = 4,
) -> list[dict]:
    """
    Get Chrome extensions relevant to a given category and goal.

    Args:
        category: Problem category (e.g., 'social media', 'seo leads').
        goal: User goal (e.g., 'save-time', 'grow-revenue').
        limit: Max number of extensions to return.

    Returns:
        Deduplicated list of extension dicts.
    """
    cat_lower = (category or "").lower()
    goal_lower = (goal or "").lower()

    extensions: list[dict] = []

    for key, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in cat_lower for kw in keywords):
            extensions.extend(CHROME_EXTENSIONS_DATA.get(key, []))

    for key, keywords in _GOAL_KEYWORDS.items():
        if any(kw in goal_lower for kw in keywords):
            extensions.extend(CHROME_EXTENSIONS_DATA.get(key, []))

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[dict] = []
    for ext in extensions:
        if ext["name"] not in seen:
            seen.add(ext["name"])
            unique.append(ext)

    return unique[:limit]
