"""
═══════════════════════════════════════════════════════════════
SUPABASE SERVICE — Lead & Conversation Management
═══════════════════════════════════════════════════════════════
Server-side Supabase operations (moved from frontend).
Handles lead CRUD, lead scoring, and conversation storage.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
from supabase import create_client, Client

from app.config import get_settings

logger = structlog.get_logger()


def _get_client() -> Client:
    """Create a Supabase client."""
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


# ── Lead Scoring ───────────────────────────────────────────────


def calculate_lead_score(lead_data: dict) -> int:
    """
    Calculate lead score (0–100) based on qualification factors.

    Ported from frontend src/lib/supabase.js → calculateLeadScore().

    Scoring breakdown:
      • Individual type: 0–25 points
      • Tech competency: 0–20 points
      • Timeline urgency: 0–25 points
      • Tried micro solutions: 0–15 points
      • Problem description quality: 0–15 points
    """
    score = 0

    # Individual type scoring (max 25)
    type_scores = {
        "founder-owner": 25,
        "sales-marketing": 20,
        "ops-admin": 18,
        "finance-legal": 18,
        "hr-recruiting": 15,
        "support-success": 15,
        "individual-student": 10,
    }
    individual_type = lead_data.get("individual_type", "")
    score += type_scores.get(individual_type, 10)

    # Tech competency (max 20) — higher = better lead
    tech_level = lead_data.get("tech_competency_level", 3)
    score += int(tech_level) * 4

    # Timeline urgency (max 25)
    urgency_scores = {
        "immediately": 25,
        "this-week": 22,
        "this-month": 18,
        "this-quarter": 12,
        "just-exploring": 5,
    }
    urgency = lead_data.get("timeline_urgency", "")
    score += urgency_scores.get(urgency, 10)

    # Tried micro solutions (max 15)
    if lead_data.get("micro_solutions_tried"):
        score += 15

    # Problem description quality (max 15)
    desc = lead_data.get("problem_description", "")
    if desc and len(desc) > 100:
        score += 15
    elif desc and len(desc) > 50:
        score += 10
    elif desc:
        score += 5

    return min(score, 100)


# ── Lead CRUD ──────────────────────────────────────────────────


async def save_lead(lead_data: dict) -> dict:
    """
    Insert a new lead into Supabase with server-side scoring.

    Args:
        lead_data: Dict of lead fields matching the leads table schema.

    Returns:
        dict with 'success' bool and 'data' or 'error'.
    """
    try:
        client = _get_client()

        # Calculate score server-side
        lead_data["lead_score"] = calculate_lead_score(lead_data)
        lead_data["status"] = lead_data.get("status", "new")

        response = (
            client.table("leads")
            .insert(lead_data)
            .execute()
        )

        logger.info(
            "Lead saved",
            lead_score=lead_data["lead_score"],
            individual_type=lead_data.get("individual_type"),
        )

        return {"success": True, "data": response.data[0] if response.data else {}}

    except Exception as e:
        logger.error("Error saving lead", error=str(e))
        return {"success": False, "error": str(e)}


async def update_lead(lead_id: str, updates: dict) -> dict:
    """
    Partially update an existing lead.

    Args:
        lead_id: The lead UUID.
        updates: Dict of fields to update.

    Returns:
        dict with 'success' bool and 'data' or 'error'.
    """
    try:
        client = _get_client()

        # Recalculate score if qualification fields changed
        scoring_fields = {
            "individual_type", "tech_competency_level",
            "timeline_urgency", "micro_solutions_tried",
            "problem_description",
        }
        if scoring_fields & set(updates.keys()):
            # Fetch the current lead and merge updates
            current = (
                client.table("leads")
                .select("*")
                .eq("id", lead_id)
                .single()
                .execute()
            )
            if current.data:
                merged = {**current.data, **updates}
                updates["lead_score"] = calculate_lead_score(merged)

        response = (
            client.table("leads")
            .update(updates)
            .eq("id", lead_id)
            .execute()
        )

        return {"success": True, "data": response.data[0] if response.data else {}}

    except Exception as e:
        logger.error("Error updating lead", lead_id=lead_id, error=str(e))
        return {"success": False, "error": str(e)}


async def get_leads(
    domain: Optional[str] = None,
    status: Optional[str] = None,
    individual_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Fetch leads with optional filters and pagination.

    Returns:
        dict with 'success', 'data' (list), and 'count'.
    """
    try:
        client = _get_client()

        query = (
            client.table("leads")
            .select("*", count="exact")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )

        if domain:
            query = query.eq("domain", domain)
        if status:
            query = query.eq("status", status)
        if individual_type:
            query = query.eq("individual_type", individual_type)

        response = query.execute()

        return {
            "success": True,
            "data": response.data or [],
            "count": response.count or 0,
        }

    except Exception as e:
        logger.error("Error fetching leads", error=str(e))
        return {"success": False, "error": str(e), "data": [], "count": 0}


# ── Conversations ──────────────────────────────────────────────


async def save_conversation(
    lead_id: str,
    messages: list[dict],
    recommendations: Optional[list] = None,
) -> dict:
    """
    Store a conversation (messages + recommendations) for a lead.

    Args:
        lead_id: The lead UUID this conversation belongs to.
        messages: List of message objects.
        recommendations: Optional list of AI recommendation objects.

    Returns:
        dict with 'success' bool and 'data' or 'error'.
    """
    try:
        client = _get_client()

        response = (
            client.table("conversations")
            .insert({
                "lead_id": lead_id,
                "messages": messages,
                "recommendations": recommendations or [],
            })
            .execute()
        )

        logger.info("Conversation saved", lead_id=lead_id, message_count=len(messages))

        return {"success": True, "data": response.data[0] if response.data else {}}

    except Exception as e:
        logger.error("Error saving conversation", lead_id=lead_id, error=str(e))
        return {"success": False, "error": str(e)}
