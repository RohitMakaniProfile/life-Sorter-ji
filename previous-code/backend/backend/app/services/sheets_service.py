"""
═══════════════════════════════════════════════════════════════
GOOGLE SHEETS SERVICE — Company Data Fetcher & Parser
═══════════════════════════════════════════════════════════════
Async CSV fetch from Google Sheets with smart row-type detection.
Ported from api/companies.js and api/search-companies.js.
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from app.services import openai_service

logger = structlog.get_logger()

# ── Sheet Configuration ────────────────────────────────────────

# Consolidated sheet (for search-companies)
CONSOLIDATED_SHEET_ID = "1d6nrGP4yRbx_ddzClAheicsavF2OsmINJmMDIQIL4m0"

# Domain-specific sheet (for companies listing)
DOMAIN_SHEET_ID = "1JKx3RwPbUL2-r5l8ayDUQfKU3kiIEg-FkFym3yJCNiw"

# Map domain IDs to actual Google Sheet tab names (case-sensitive)
DOMAIN_TO_SHEET = {
    "marketing": "Marketing",
    "sales-support": "Sales and support",
    "social-media": "Social media",
    "legal": "Legal",
    "hr-hiring": "HR",
    "finance": "Finance",
    "supply-chain": "Supply chain",
    "research": "Research",
    "data-analysis": "Data",
}

# Known domain labels (for row type detection in consolidated sheet)
DOMAIN_LABELS = [
    "LEGAL", "MARKETING", "SALES", "HR", "FINANCE",
    "SUPPLY CHAIN", "RESEARCH", "DATA", "SOCIAL MEDIA", "CUSTOMER SUPPORT",
]

# Priority column names for matching (highest weight)
PRIORITY_COLUMNS = {
    "name": ["Startup name", "Startup Name", "Company", "Name", "Company Name"],
    "country": ["Country", "Location", "Region"],
    "problem": ["Basic problem", "Basic Problem", "Problem", "Problem Statement", "What they solve"],
    "description": [
        "Core product description (<=3 lines)", "Core product description",
        "Description", "Product Description", "What they do",
    ],
    "product_description": ["Product description", "Product Description", "Full Description"],
}

# Secondary columns (for tie-breaking only)
SECONDARY_COLUMNS = {
    "differentiator": ["Differentiator", "Unique Value", "USP", "What makes them special"],
    "ai_advantage": ["Main AI / data advantage", "Main AI/data advantage", "AI Advantage", "Tech Advantage"],
    "funding_amount": ["Latest Funding Amount", "Funding", "Funding Amount"],
    "funding_date": ["Latest Funding Date", "Funding Date"],
    "pricing": ["Pricing motion & segment", "Pricing", "Price", "Pricing Model"],
}

# Header row indicators
HEADER_INDICATORS = [
    "startup name", "company", "country", "basic problem",
    "core product", "description", "differentiator",
]


# ── CSV Helpers ────────────────────────────────────────────────


def _build_csv_url(sheet_id: str, sheet_name: str | None = None) -> str:
    """Build Google Sheets CSV export URL."""
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    if sheet_name:
        base += f"&sheet={httpx.URL(sheet_name)}"
    return base


def _detect_row_type(row: list[str]) -> str:
    """Detect whether a CSV row is a domain header, column header, or startup record."""
    if not row:
        return "empty"

    first_cell = (row[0] or "").strip().upper()
    non_empty = [c for c in row if c and c.strip()]

    # Domain header: single label like "LEGAL", most cells empty
    if len(non_empty) <= 2:
        for label in DOMAIN_LABELS:
            if first_cell == label or label in first_cell or first_cell in label:
                return "domain-header"

    # Column header: multiple known header keywords
    lower_row = [(c or "").lower() for c in row]
    header_matches = sum(
        1 for h in HEADER_INDICATORS
        if any(h in cell for cell in lower_row)
    )
    if header_matches >= 3:
        return "column-header"

    # Startup record: has a name and at least 2 priority fields
    has_name = bool(first_cell) and len(first_cell) > 1
    if has_name and not any(first_cell == d for d in DOMAIN_LABELS):
        filled_priority = sum(
            1 for c in row[:5]
            if c and len(c.strip()) > 3
        )
        if filled_priority >= 2:
            return "startup-record"

    return "unknown"


def _get_column_value(row: list[str], headers: list[str], possible_names: list[str]) -> str:
    """Get a column value by flexible header matching."""
    for name in possible_names:
        for idx, header in enumerate(headers):
            h_lower = (header or "").lower()
            n_lower = name.lower()
            if h_lower == n_lower or n_lower.split(" ")[0] in h_lower:
                if idx < len(row) and row[idx]:
                    return row[idx].strip()
    return ""


async def _fetch_csv(url: str) -> str:
    """Fetch CSV text from a URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


# ── Public API ─────────────────────────────────────────────────


async def fetch_companies_by_domain(domain: str | None = None) -> dict:
    """
    Fetch companies from a domain-specific Google Sheet tab.
    Port of api/companies.js.

    Args:
        domain: Domain slug (e.g., 'social-media', 'legal'). Defaults to 'Social media'.

    Returns:
        dict with 'success', 'count', and 'companies' list.
    """
    sheet_name = DOMAIN_TO_SHEET.get(domain or "", "Social media")
    url = f"https://docs.google.com/spreadsheets/d/{DOMAIN_SHEET_ID}/gviz/tq?tqx=out:csv&sheet={sheet_name}"

    try:
        csv_text = await _fetch_csv(url)

        reader = csv.DictReader(io.StringIO(csv_text))
        companies = []

        for row in reader:
            # Normalize column names
            name = row.get("Startup name") or row.get("Startup Name") or ""
            if not name.strip():
                continue

            companies.append({
                "name": name.strip(),
                "country": row.get("Country", "").strip(),
                "problem": row.get("Basic problem") or row.get("Basic Problem") or "",
                "differentiator": row.get("Differentiator", "").strip(),
                "description": (
                    row.get("Core product description (<=3 lines)")
                    or row.get("Core product description")
                    or ""
                ).strip(),
                "aiAdvantage": (
                    row.get("Main AI / data advantage")
                    or row.get("Main AI/data advantage")
                    or ""
                ).strip(),
                "fundingAmount": row.get("Latest Funding Amount", "").strip(),
                "fundingDate": row.get("Latest Funding Date", "").strip(),
                "pricing": row.get("Pricing motion & segment", "").strip(),
            })

        logger.info("Companies fetched", domain=domain, count=len(companies))

        return {"success": True, "count": len(companies), "companies": companies}

    except Exception as e:
        logger.error("Failed to fetch companies", domain=domain, error=str(e))
        return {"success": False, "count": 0, "companies": [], "error": str(e)}


async def search_companies(
    domain: str | None = None,
    subdomain: str | None = None,
    requirement: str | None = None,
    user_context: dict | None = None,
) -> dict:
    """
    AI-powered priority search across the consolidated company sheet.
    Port of api/search-companies.js.

    Args:
        domain: Target domain.
        subdomain: Target subdomain.
        requirement: User's search requirement text.
        user_context: User profile context dict.

    Returns:
        dict with matched companies, explanations, and metadata.
    """
    url = f"https://docs.google.com/spreadsheets/d/{CONSOLIDATED_SHEET_ID}/gviz/tq?tqx=out:csv"

    try:
        csv_text = await _fetch_csv(url)

        # Parse without headers to detect row types
        reader = csv.reader(io.StringIO(csv_text))
        raw_rows = [row for row in reader if any(cell.strip() for cell in row)]

        # Process rows: detect domains, headers, and startup records
        current_domain = "General"
        current_headers: list[str] = []
        startups: list[dict] = []

        for i, row in enumerate(raw_rows):
            row_type = _detect_row_type(row)

            if row_type == "domain-header":
                current_domain = (row[0] or "General").strip()

            elif row_type == "column-header":
                current_headers = [h.strip() for h in row]

            elif row_type == "startup-record" and current_headers:
                name = _get_column_value(row, current_headers, PRIORITY_COLUMNS["name"])
                country = _get_column_value(row, current_headers, PRIORITY_COLUMNS["country"])
                problem = _get_column_value(row, current_headers, PRIORITY_COLUMNS["problem"])
                description = _get_column_value(row, current_headers, PRIORITY_COLUMNS["description"])
                product_desc = _get_column_value(row, current_headers, PRIORITY_COLUMNS["product_description"])
                differentiator = _get_column_value(row, current_headers, SECONDARY_COLUMNS["differentiator"])
                ai_advantage = _get_column_value(row, current_headers, SECONDARY_COLUMNS["ai_advantage"])
                pricing = _get_column_value(row, current_headers, SECONDARY_COLUMNS["pricing"])

                if name and len(name) > 1:
                    priority_text = " ".join(
                        filter(None, [name, country, problem, description, product_desc])
                    ).lower()

                    startups.append({
                        "name": name,
                        "country": country,
                        "problem": problem,
                        "description": description or product_desc,
                        "differentiator": differentiator,
                        "aiAdvantage": ai_advantage,
                        "pricing": pricing,
                        "domain": current_domain,
                        "rowNumber": i + 1,
                        "priorityText": priority_text,
                    })

        if not startups:
            return {
                "success": True,
                "companies": [],
                "message": "No startups found in the database",
            }

        # No requirement → return domain matches
        if not requirement:
            domain_matches = startups
            if domain:
                domain_matches = [
                    s for s in startups
                    if domain.lower() in s["domain"].lower()
                ]
            return {
                "success": True,
                "companies": domain_matches[:10],
                "totalCount": len(startups),
            }

        # Build user profile
        user_profile = _build_user_profile(user_context)

        settings = get_settings()
        if not settings.openai_api_key_active:
            # Fallback: keyword matching
            return _keyword_search(startups, requirement, domain)

        # GPT-powered priority search
        startup_summaries = "\n\n".join(
            f"[{i}] {s['name']} ({s['country'] or 'Global'}) "
            f"[Domain: {s['domain']}] [Row: {s['rowNumber']}]\n"
            f"Problem: {s['problem'] or 'N/A'}\n"
            f"Description: {s['description'] or 'N/A'}"
            for i, s in enumerate(startups)
        )

        search_prompt = f"""You are an AI search assistant that matches user requirements to startups.

PRIORITY SEARCH RULES:
1. Search ONLY using these fields (in order of importance):
   - Basic problem (weight: +4 for direct match)
   - Core product/description (weight: +3 for direct match)
   - Startup name (weight: +1 if obviously indicates category)
   - Country (weight: +1 if user specified preference)
   - Domain (weight: +1 if matches user's domain)

2. SCORING:
   - Score 8-10: Excellent match (problem directly addresses user need)
   - Score 6-7: Good match (description relates to user need)
   - Score 4-5: Partial match (some keyword overlap)
   - Score 0-3: Weak match

3. ALWAYS find TOP 3 matches - there is always a best fit.

{user_profile}

User's domain context: {f'{subdomain} in {domain}' if subdomain else domain or 'General business'}
User's requirement: "{requirement}"

Available startups ({len(startups)} total):
{startup_summaries}

Return EXACTLY this JSON format:
{{
  "topMatches": [
    {{"index": 0, "score": 9, "matchReason": "Two bullet points explaining why"}},
    {{"index": 2, "score": 7, "matchReason": "Two bullet points explaining why"}},
    {{"index": 5, "score": 6, "matchReason": "Two bullet points explaining why"}}
  ],
  "alternatives": [{{"index": 8, "score": 5}}, {{"index": 12, "score": 4}}]
}}"""

        search_response = await openai_service.company_search_gpt(search_prompt, requirement)

        # Parse GPT response
        matched_results = _parse_search_response(search_response)

        # Map results to startup data
        top_matches = []
        for match in (matched_results.get("topMatches") or [])[:3]:
            idx = match.get("index", -1)
            if 0 <= idx < len(startups):
                top_matches.append({
                    **startups[idx],
                    "matchScore": match.get("score", 0),
                    "matchReason": match.get("matchReason", ""),
                })

        alternatives = []
        for match in (matched_results.get("alternatives") or [])[:4]:
            idx = match.get("index", -1)
            if 0 <= idx < len(startups):
                alternatives.append({
                    **startups[idx],
                    "matchScore": match.get("score", 0),
                })

        # Fallback if no matches
        if not top_matches:
            top_matches = [
                {**s, "matchScore": 5 - i, "matchReason": "Closest available match"}
                for i, s in enumerate(startups[:3])
            ]

        # Generate helpful explanation
        helpful_response = await _generate_explanation(
            top_matches, requirement, domain, subdomain, user_profile
        )

        return {
            "success": True,
            "companies": top_matches,
            "alternatives": alternatives,
            "totalCount": len(startups),
            "searchMethod": "priority-ai",
            "helpfulResponse": helpful_response,
            "userRequirement": requirement,
        }

    except Exception as e:
        logger.error("Company search failed", error=str(e))
        return {"success": False, "companies": [], "error": str(e)}


# ── Private Helpers ────────────────────────────────────────────


def _build_user_profile(user_context: dict | None) -> str:
    """Build a user profile string from context."""
    if not user_context:
        return ""

    role = user_context.get("role", "")
    if role == "business-owner":
        return (
            f"User Profile: Business Owner\n"
            f"- Business type: {user_context.get('businessType', 'Not specified')}\n"
            f"- Industry: {user_context.get('industry', 'Not specified')}\n"
            f"- Target audience: {user_context.get('targetAudience', 'Not specified')}\n"
            f"- Market segment: {user_context.get('marketSegment', 'Not specified')}"
        )
    elif role == "professional":
        profile = (
            f"User Profile: Working Professional\n"
            f"- Role & Industry: {user_context.get('roleAndIndustry', 'Not specified')}\n"
            f"- Solution for: {user_context.get('solutionFor', 'Not specified')}"
        )
        if user_context.get("salaryContext"):
            profile += f"\n- Context: {user_context['salaryContext']}"
        return profile
    elif role == "freelancer":
        return (
            f"User Profile: Freelancer\n"
            f"- Type of work: {user_context.get('freelanceType', 'Not specified')}\n"
            f"- Main challenge: {user_context.get('challenge', 'Not specified')}"
        )
    elif role == "student":
        return "User Profile: Student/Learner exploring solutions"

    return ""


def _keyword_search(startups: list[dict], requirement: str, domain: str | None) -> dict:
    """Fallback keyword-based search when no OpenAI key is available."""
    requirement_lower = requirement.lower()
    keywords = [w for w in requirement_lower.split() if len(w) > 3]

    scored = []
    for s in startups:
        score = sum(2 for kw in keywords if kw in s["priorityText"])
        if domain and domain.lower() in s["domain"].lower():
            score += 1
        scored.append({**s, "matchScore": score})

    scored.sort(key=lambda x: x["matchScore"], reverse=True)

    return {
        "success": True,
        "companies": scored[:3],
        "totalCount": len(startups),
        "searchMethod": "keyword-fallback",
    }


def _parse_search_response(response_text: str) -> dict:
    """Extract JSON from GPT search response."""
    try:
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        # Fallback: extract any numbers
        numbers = re.findall(r"\d+", response_text)
        if numbers:
            return {
                "topMatches": [
                    {"index": int(n), "score": 7 - i, "matchReason": "Matches your requirements"}
                    for i, n in enumerate(numbers[:3])
                ]
            }
    return {"topMatches": [], "alternatives": []}


async def _generate_explanation(
    top_matches: list[dict],
    requirement: str,
    domain: str | None,
    subdomain: str | None,
    user_profile: str,
) -> str:
    """Generate a helpful explanation of matched companies."""
    match_text = "\n".join(
        f"**{i + 1}. {c['name']}** ({c.get('country', 'Global')}) "
        f"[Score: {c.get('matchScore', 0)}/10]\n"
        f"- Problem solved: {c.get('problem', 'Business automation')}\n"
        f"- What they do: {c.get('description', 'AI solution')}\n"
        f"- Why it matches: {c.get('matchReason', 'Relevant to your need')}\n"
        f"- Row #{c.get('rowNumber', 'N/A')}\n"
        for i, c in enumerate(top_matches)
    )

    context_str = f"{subdomain} in {domain}" if subdomain else domain or "their business"

    explanation_prompt = f"""You are a friendly business advisor helping someone find AI tools.
Write in VERY SIMPLE language - like explaining to a friend.

{user_profile}

User needs: "{requirement}"
Context: {context_str}

TOP MATCHES FOUND:
{match_text}

Write a helpful response:
1. Start with "Based on what you're looking for..." (1 sentence)
2. For each tool, explain in 2-3 simple sentences:
   - What it does
   - How it helps with their specific need
3. End with encouragement

RULES:
- NEVER say "no matches" or "not perfect"
- Be positive and show how each tool helps
- Use everyday language, no jargon
- Keep under 250 words"""

    try:
        return await openai_service.company_explanation_gpt(explanation_prompt, requirement)
    except Exception:
        return ""
