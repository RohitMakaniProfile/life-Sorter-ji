"""
═══════════════════════════════════════════════════════════════
CUSTOM GPTS DATA — Extracted from ChatBotNew.jsx
═══════════════════════════════════════════════════════════════
Custom GPT recommendations mapped to problem categories.
Used by the recommendations router.
"""

from __future__ import annotations

CUSTOM_GPTS_DATA: dict[str, list[dict]] = {
    "content-creation": [
        {"name": "Canva GPT", "url": "https://chat.openai.com/g/canva", "description": "Design social posts with AI", "rating": "4.8"},
        {"name": "Copywriter GPT", "url": "https://chat.openai.com/g/copywriter", "description": "Write converting ad copy", "rating": "4.7"},
        {"name": "Video Script Writer", "url": "https://chat.openai.com/g/video-script", "description": "Scripts for YouTube & Reels", "rating": "4.6"},
    ],
    "seo-marketing": [
        {"name": "SEO GPT", "url": "https://chat.openai.com/g/seo", "description": "Keyword research & optimization", "rating": "4.8"},
        {"name": "Blog Post Generator", "url": "https://chat.openai.com/g/blog-generator", "description": "SEO-optimized articles", "rating": "4.7"},
        {"name": "Landing Page Expert", "url": "https://chat.openai.com/g/landing-page", "description": "High-converting page copy", "rating": "4.5"},
    ],
    "sales-leads": [
        {"name": "Cold Email GPT", "url": "https://chat.openai.com/g/cold-email", "description": "Personalized outreach emails", "rating": "4.6"},
        {"name": "Sales Pitch Creator", "url": "https://chat.openai.com/g/sales-pitch", "description": "Compelling sales scripts", "rating": "4.5"},
        {"name": "LinkedIn Outreach", "url": "https://chat.openai.com/g/linkedin-outreach", "description": "Professional connection messages", "rating": "4.4"},
    ],
    "automation": [
        {"name": "Automation Expert", "url": "https://chat.openai.com/g/automation", "description": "Design workflow automations", "rating": "4.7"},
        {"name": "Zapier Helper", "url": "https://chat.openai.com/g/zapier-helper", "description": "Build Zaps step by step", "rating": "4.5"},
        {"name": "Excel Formula GPT", "url": "https://chat.openai.com/g/excel-formula", "description": "Complex formulas explained", "rating": "4.8"},
    ],
    "data-analysis": [
        {"name": "Data Analyst GPT", "url": "https://chat.openai.com/g/data-analyst", "description": "Analyze data & create charts", "rating": "4.9"},
        {"name": "SQL Expert", "url": "https://chat.openai.com/g/sql-expert", "description": "Write & optimize queries", "rating": "4.7"},
        {"name": "Dashboard Designer", "url": "https://chat.openai.com/g/dashboard", "description": "Plan effective dashboards", "rating": "4.5"},
    ],
    "legal-contracts": [
        {"name": "Contract Reviewer", "url": "https://chat.openai.com/g/contract-review", "description": "Spot risky clauses", "rating": "4.6"},
        {"name": "Legal Document Drafter", "url": "https://chat.openai.com/g/legal-drafter", "description": "Draft basic agreements", "rating": "4.5"},
    ],
    "hr-recruiting": [
        {"name": "Job Description Writer", "url": "https://chat.openai.com/g/job-description", "description": "Compelling job posts", "rating": "4.7"},
        {"name": "Interview Question GPT", "url": "https://chat.openai.com/g/interview-questions", "description": "Role-specific questions", "rating": "4.6"},
        {"name": "Resume Reviewer", "url": "https://chat.openai.com/g/resume-reviewer", "description": "Screen candidates faster", "rating": "4.5"},
    ],
    "customer-support": [
        {"name": "Support Response GPT", "url": "https://chat.openai.com/g/support-response", "description": "Draft customer replies", "rating": "4.6"},
        {"name": "FAQ Generator", "url": "https://chat.openai.com/g/faq-generator", "description": "Build knowledge bases", "rating": "4.5"},
    ],
    "personal-productivity": [
        {"name": "Task Prioritizer", "url": "https://chat.openai.com/g/task-prioritizer", "description": "Organize your to-dos", "rating": "4.7"},
        {"name": "Meeting Summarizer", "url": "https://chat.openai.com/g/meeting-summarizer", "description": "Notes from transcripts", "rating": "4.8"},
        {"name": "Learning Coach", "url": "https://chat.openai.com/g/learning-coach", "description": "Personalized study plans", "rating": "4.6"},
    ],
}


# ── Category Matching Logic ────────────────────────────────────

_GPT_CATEGORY_KEYWORDS = {
    "content-creation": ["content", "social", "video"],
    "seo-marketing": ["seo", "blog", "landing"],
    "sales-leads": ["lead", "sales", "outreach"],
    "automation": ["automate", "excel"],
    "data-analysis": ["dashboard", "data", "analytics"],
    "legal-contracts": ["contract", "legal"],
    "hr-recruiting": ["hire", "interview", "recruit"],
    "customer-support": ["support", "ticket", "customer"],
    "personal-productivity": ["plan", "learning"],
}

_GPT_GOAL_KEYWORDS = {
    "automation": ["save-time"],
    "personal-productivity": ["personal"],
}

_GPT_ROLE_KEYWORDS = {
    "legal-contracts": ["legal"],
    "hr-recruiting": ["hr"],
}


def get_relevant_gpts(
    category: str = "",
    goal: str = "",
    role: str = "",
    limit: int = 3,
) -> list[dict]:
    """
    Get Custom GPTs relevant to a given category, goal, and role.

    Args:
        category: Problem category keyword.
        goal: User goal keyword.
        role: User role keyword.
        limit: Max number of GPTs to return.

    Returns:
        Deduplicated list of GPT dicts.
    """
    cat_lower = (category or "").lower()
    goal_lower = (goal or "").lower()
    role_lower = (role or "").lower()

    gpts: list[dict] = []

    for key, keywords in _GPT_CATEGORY_KEYWORDS.items():
        if any(kw in cat_lower for kw in keywords):
            gpts.extend(CUSTOM_GPTS_DATA.get(key, []))

    for key, keywords in _GPT_GOAL_KEYWORDS.items():
        if any(kw in goal_lower for kw in keywords):
            gpts.extend(CUSTOM_GPTS_DATA.get(key, []))

    for key, keywords in _GPT_ROLE_KEYWORDS.items():
        if any(kw in role_lower for kw in keywords):
            gpts.extend(CUSTOM_GPTS_DATA.get(key, []))

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[dict] = []
    for gpt in gpts:
        if gpt["name"] not in seen:
            seen.add(gpt["name"])
            unique.append(gpt)

    return unique[:limit]
