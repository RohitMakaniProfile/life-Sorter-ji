"""
═══════════════════════════════════════════════════════════════
POSTGRES SERVICE — Lead & Conversation Management
═══════════════════════════════════════════════════════════════
Replaces the old Supabase-backed implementation with PostgreSQL (asyncpg).
Handles lead CRUD, lead scoring, and lead conversation storage.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog
import json

from app.db import get_pool

logger = structlog.get_logger()


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
        # Calculate score server-side
        lead_data["lead_score"] = calculate_lead_score(lead_data)
        lead_data["status"] = lead_data.get("status", "new")
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO leads (
                    domain, website_url,
                    individual_type, tech_competency_level, timeline_urgency,
                    micro_solutions_tried, problem_description,
                    lead_score, status
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                RETURNING *
                """,
                lead_data.get("domain"),
                lead_data.get("website_url"),
                lead_data.get("individual_type"),
                lead_data.get("tech_competency_level"),
                lead_data.get("timeline_urgency"),
                lead_data.get("micro_solutions_tried"),
                lead_data.get("problem_description"),
                int(lead_data.get("lead_score") or 0),
                lead_data.get("status") or "new",
            )

        logger.info(
            "Lead saved",
            lead_score=lead_data["lead_score"],
            individual_type=lead_data.get("individual_type"),
        )

        return {"success": True, "data": dict(row) if row else {}}

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
        # Recalculate score if qualification fields changed
        scoring_fields = {
            "individual_type", "tech_competency_level",
            "timeline_urgency", "micro_solutions_tried",
            "problem_description",
        }
        if scoring_fields & set(updates.keys()):
            pool = get_pool()
            async with pool.acquire() as conn:
                current = await conn.fetchrow("SELECT * FROM leads WHERE id = $1::uuid", lead_id)
            if current:
                merged = {**dict(current), **updates}
                updates["lead_score"] = calculate_lead_score(merged)

        set_parts = []
        values = []
        mapping = {
            "domain": "domain",
            "website_url": "website_url",
            "individual_type": "individual_type",
            "tech_competency_level": "tech_competency_level",
            "timeline_urgency": "timeline_urgency",
            "micro_solutions_tried": "micro_solutions_tried",
            "problem_description": "problem_description",
            "lead_score": "lead_score",
            "status": "status",
        }
        for k, col in mapping.items():
            if k in updates:
                set_parts.append(f"{col} = ${len(values) + 1}")
                values.append(updates[k])
        if not set_parts:
            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM leads WHERE id = $1::uuid", lead_id)
            return {"success": True, "data": dict(row) if row else {}}

        set_parts.append(f"updated_at = NOW()")
        values.append(lead_id)
        q = f"UPDATE leads SET {', '.join(set_parts)} WHERE id = ${len(values)}::uuid RETURNING *"
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(q, *values)
        return {"success": True, "data": dict(row) if row else {}}

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
        where = []
        values = []
        if domain:
            where.append(f"domain = ${len(values) + 1}")
            values.append(domain)
        if status:
            where.append(f"status = ${len(values) + 1}")
            values.append(status)
        if individual_type:
            where.append(f"individual_type = ${len(values) + 1}")
            values.append(individual_type)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        pool = get_pool()
        async with pool.acquire() as conn:
            count = int(
                await conn.fetchval(f"SELECT COUNT(*) FROM leads {where_sql}", *values)
            )
            q = f"""
            SELECT *
            FROM leads
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ${len(values) + 1} OFFSET ${len(values) + 2}
            """
            rows = await conn.fetch(q, *values, int(limit), int(offset))
        return {"success": True, "data": [dict(r) for r in rows], "count": count}

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
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO lead_conversations (lead_id, messages, recommendations)
                VALUES ($1::uuid, $2::jsonb, $3::jsonb)
                RETURNING *
                """,
                lead_id,
                json.dumps(messages or []),
                json.dumps(recommendations or []),
            )

        logger.info("Conversation saved", lead_id=lead_id, message_count=len(messages))

        return {"success": True, "data": dict(row) if row else {}}

    except Exception as e:
        logger.error("Error saving conversation", lead_id=lead_id, error=str(e))
        return {"success": False, "error": str(e)}
