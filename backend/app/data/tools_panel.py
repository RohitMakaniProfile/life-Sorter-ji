"""
═══════════════════════════════════════════════════════════════
INSTANT TOOL PANEL — Hardcoded deterministic tool lookup
═══════════════════════════════════════════════════════════════
Returns the best tools for a given Outcome × Domain × Task
in <5ms — no LLM, no RAG, no network calls.

Data source: tools_lookup.json (built from comprehensive_dataset.xlsx
+ matched_tools_by_persona.json)
"""

import json
from pathlib import Path
from functools import lru_cache

import structlog

logger = structlog.get_logger()

_LOOKUP_PATH = Path(__file__).parent / "tools_lookup.json"


@lru_cache(maxsize=1)
def _load_lookup() -> dict:
    """Load the tool lookup JSON once and cache in memory."""
    with open(_LOOKUP_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Fuzzy domain matching ──────────────────────────────────────
# Frontend domain names → Persona keys in the dataset
_DOMAIN_TO_PERSONA = {
    # lead-generation
    "Content & Social Media": "Content & Social Media",
    "SEO & Organic Visibility": "SEO & Organic Visibility",
    "Paid Media & Ads": "Paid Media & Ads",
    "B2B Lead Generation": "B2B Lead Generation",
    # sales-retention
    "Sales Execution & Enablement": "Sales Execution & Enablement",
    "Lead Management & Conversion": "Lead Management & Conversion",
    "Customer Success & Reputation": "Customer Success & Reputation",
    "Repeat Sales": "Customer Success & Reputation",
    # business-strategy
    "Business Intelligence & Analytics": "Business Intelligence & Analytics",
    "Market Strategy & Innovation": "Market Strategy & Innovation",
    "Financial Health & Risk": "Financial Health & Risk",
    "Org Efficiency & Hiring": "Org Efficiency & Hiring",
    "Improve Yourself": "Owner & Founder Improvements",
    # save-time
    "Sales & Content Automation": "Marketing & Sales Automation",
    "Finance Legal & Admin": "Finance Legal & Admin",
    "Customer Support Ops": "Customer Support Ops",
    "Recruiting & HR Ops": "Recruiting & HR Ops",
    "Personal & Team Productivity": "Personal & Team Productivity",
}

# ── Outcome ID mapping from frontend ──────────────────────────
_OUTCOME_LABEL_TO_ID = {
    "Lead Generation": "lead-generation",
    "Lead Generation (Marketing, SEO & Social)": "lead-generation",
    "Sales & Retention": "sales-retention",
    "Sales & Retention (Calling, Support & Expansion)": "sales-retention",
    "Business Strategy": "business-strategy",
    "Business Strategy (Intelligence, Market & Org)": "business-strategy",
    "Save Time": "save-time",
    "Save Time (Automation Workflow, Extract PDF, Bulk Task)": "save-time",
}


def get_instant_tools(
    outcome_label: str,
    domain: str,
    task: str,
    limit: int = 5,
) -> dict:
    """
    Instant deterministic tool lookup — returns top tools in <5ms.

    Strategy:
    1. Match outcome_label → outcome_id
    2. Match domain → persona key
    3. Get tools from that outcome×persona bucket
    4. Score by task keyword overlap + composite_score
    5. Fall back to 'general' pool if primary bucket is thin
    6. Return top N sorted by relevance

    Returns dict with 'tools' list and 'message' string.
    """
    lookup = _load_lookup()

    # ── Resolve outcome ID ─────────────────────────────────────
    outcome_id = _OUTCOME_LABEL_TO_ID.get(outcome_label, "")
    if not outcome_id:
        # Try partial match
        label_lower = outcome_label.lower()
        for key, oid in _OUTCOME_LABEL_TO_ID.items():
            if key.lower() in label_lower or label_lower in key.lower():
                outcome_id = oid
                break
    if not outcome_id:
        outcome_id = "general"

    # ── Resolve persona ────────────────────────────────────────
    persona = _DOMAIN_TO_PERSONA.get(domain, domain)

    # ── Gather candidate tools ─────────────────────────────────
    candidates = []

    # Primary: outcome-specific bucket
    if outcome_id in lookup and persona in lookup[outcome_id]:
        candidates.extend(lookup[outcome_id][persona])

    # Supplement from 'general' pool
    if "general" in lookup and persona in lookup["general"]:
        existing_names = {t["name"].lower() for t in candidates}
        for t in lookup["general"][persona]:
            if t["name"].lower() not in existing_names:
                candidates.append(t)

    # If still empty, try all personas in the outcome
    if not candidates and outcome_id in lookup:
        for p_tools in lookup[outcome_id].values():
            candidates.extend(p_tools)

    # Last resort: general pool, all personas
    if not candidates and "general" in lookup:
        for p_tools in lookup["general"].values():
            candidates.extend(p_tools)

    if not candidates:
        return {"tools": [], "message": ""}

    # ── Score by task keyword relevance ────────────────────────
    task_words = set(
        w.lower() for w in task.replace("/", " ").replace("&", " ").split()
        if len(w) > 2
    )

    scored = []
    for tool in candidates:
        # Keyword overlap with task in tool's tasks field + description + name
        search_text = (
            (tool.get("tasks", "") + " " + tool.get("description", "") + " " + tool.get("name", ""))
            .lower()
        )
        keyword_hits = sum(1 for w in task_words if w in search_text)

        # Composite score from dataset (0-1 range, higher = better)
        composite = tool.get("composite_score", 0.5)

        # Combined score: keyword relevance weighted higher, then quality
        score = (keyword_hits * 3) + (composite * 10)
        scored.append((score, tool))

    # Sort descending and deduplicate by name
    scored.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    top_tools = []
    for _, tool in scored:
        name_key = tool["name"].lower().strip()
        if name_key in seen:
            continue
        seen.add(name_key)
        top_tools.append(tool)
        if len(top_tools) >= limit:
            break

    # ── Format output ──────────────────────────────────────────
    formatted = []
    for t in top_tools:
        # Build why_relevant from review summary or key pros
        why = ""
        if t.get("key_pros"):
            # Take first pro as the reason
            first_pro = t["key_pros"].split("\n")[0].strip().lstrip("•").strip()
            if first_pro:
                why = first_pro

        # Build implementation stage from composite score
        score = t.get("composite_score", 0.5)
        if score >= 0.8:
            impl_stage = "Day 1 — Start using immediately"
        elif score >= 0.65:
            impl_stage = "Week 1 — Quick setup, fast results"
        else:
            impl_stage = "Week 2 — Worth exploring after basics are set"

        # Rating display
        rating = t.get("rating", "") or t.get("g2_rating", "")

        # Review count for social proof
        reviews = t.get("total_reviews", "")

        formatted.append({
            "name": t["name"],
            "description": t.get("description", "")[:200],
            "url": t.get("url", ""),
            "category": t.get("category", ""),
            "rating": str(rating) if rating else None,
            "why_relevant": why or f"Top-rated tool for {domain}",
            "implementation_stage": impl_stage,
            "issue_solved": t.get("review_summary", "")[:150] if t.get("review_summary") else f"Addresses key challenges in {task.lower()}",
            "ease_of_use": f"⭐ {rating}" + (f" ({reviews} reviews)" if reviews else "") if rating else "Highly rated by peers",
            "source": t.get("source", ""),
        })

    message = (
        f"Based on your goal and domain, here are the top-rated tools — "
        f"curated from {len(candidates)} verified options. "
        f"Let me dig deeper into your situation to find the *exact* fit."
    )

    logger.info(
        "Instant tool panel served",
        outcome=outcome_id,
        persona=persona,
        task=task[:50],
        candidates=len(candidates),
        returned=len(formatted),
    )

    return {"tools": formatted, "message": message}
