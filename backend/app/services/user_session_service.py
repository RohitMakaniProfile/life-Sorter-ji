"""
═══════════════════════════════════════════════════════════════
USER SESSION PERSISTENCE — Supabase Sync for Session Data
═══════════════════════════════════════════════════════════════
Persists the in-memory SessionContext to the `user_sessions`
table in Supabase after every meaningful state change.

Called from session_store.py on every update_session().
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import structlog
from supabase import create_client, Client

from app.config import get_settings

logger = structlog.get_logger()


def _get_client() -> Client:
    """Create a Supabase client (reuses the same config as supabase_service)."""
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)


def _session_to_row(session) -> dict[str, Any]:
    """
    Convert an in-memory SessionContext to a dict matching
    the user_sessions table schema.
    """
    # Serialize questions_answers list
    qa_list = []
    for qa in session.questions_answers:
        qa_list.append({
            "question": qa.question,
            "answer": qa.answer,
            "question_type": qa.question_type,
        })

    # Serialize LLM call log (strip large fields to keep row size manageable)
    llm_log = []
    for call in session.llm_call_log:
        llm_log.append({
            "timestamp": call.timestamp,
            "service": call.service,
            "model": call.model,
            "purpose": call.purpose,
            "latency_ms": call.latency_ms,
            "token_usage": call.token_usage,
            "error": call.error,
        })

    # Merge all recommended tools into a single final_recommendations list
    final_recs = []
    for ext in session.recommended_extensions:
        final_recs.append({**ext, "category": "extension"})
    for gpt in session.recommended_gpts:
        final_recs.append({**gpt, "category": "gpt"})
    for comp in session.recommended_companies:
        final_recs.append({**comp, "category": "company"})

    return {
        "session_id": session.session_id,
        "updated_at": datetime.utcnow().isoformat(),

        # Flow stage
        "stage": session.stage.value if hasattr(session.stage, "value") else str(session.stage),
        "flow_completed": session.stage.value == "complete" if hasattr(session.stage, "value") else False,

        # Static Q1-Q3
        "outcome": session.outcome,
        "outcome_label": session.outcome_label,
        "domain": session.domain,
        "task": session.task,

        # Full Q&A
        "questions_answers": qa_list,

        # Website & crawl
        "website_url": session.website_url,
        "gbp_url": session.gbp_url,
        "crawl_summary": session.crawl_summary or {},
        "audience_insights": session.audience_insights or {},

        # Business profile
        "business_profile": session.business_profile or {},

        # RCA
        "rca_history": session.rca_history or [],
        "rca_summary": session.rca_summary or None,
        "rca_complete": session.rca_complete,

        # Recommendations
        "early_recommendations": session.early_recommendations or [],
        "final_recommendations": final_recs,

        # Persona
        "persona_doc_name": session.persona_doc_name,
        "llm_call_log": llm_log,
    }


async def upsert_session(session) -> dict:
    """
    Insert or update the user_sessions row for this session.

    Uses Supabase upsert on the unique session_id column so:
      - First call → INSERT
      - Subsequent calls → UPDATE
    """
    try:
        client = _get_client()
        row = _session_to_row(session)

        response = (
            client.table("user_sessions")
            .upsert(row, on_conflict="session_id")
            .execute()
        )

        logger.debug(
            "Session persisted to Supabase",
            session_id=session.session_id,
            stage=row["stage"],
        )

        return {"success": True, "data": response.data[0] if response.data else {}}

    except Exception as e:
        # Log but don't crash — persistence is best-effort,
        # the in-memory session remains the source of truth.
        logger.error(
            "Failed to persist session to Supabase",
            session_id=session.session_id,
            error=str(e),
        )
        return {"success": False, "error": str(e)}


async def update_session_auth(
    session_id: str,
    google_id: Optional[str] = None,
    google_email: Optional[str] = None,
    google_name: Optional[str] = None,
    google_avatar_url: Optional[str] = None,
    mobile_number: Optional[str] = None,
    otp_verified: bool = False,
    auth_provider: Optional[str] = None,
) -> dict:
    """
    Update only the auth-related fields for a session.
    Called when user completes Google login or OTP verification.
    """
    try:
        client = _get_client()

        updates: dict[str, Any] = {}
        if google_id is not None:
            updates["google_id"] = google_id
        if google_email is not None:
            updates["google_email"] = google_email
        if google_name is not None:
            updates["google_name"] = google_name
        if google_avatar_url is not None:
            updates["google_avatar_url"] = google_avatar_url
        if mobile_number is not None:
            updates["mobile_number"] = mobile_number
        if otp_verified:
            updates["otp_verified"] = True
        if auth_provider is not None:
            updates["auth_provider"] = auth_provider

        if updates:
            updates["auth_completed_at"] = datetime.utcnow().isoformat()

            response = (
                client.table("user_sessions")
                .update(updates)
                .eq("session_id", session_id)
                .execute()
            )

            logger.info(
                "Session auth updated",
                session_id=session_id,
                auth_provider=auth_provider,
            )
            return {"success": True, "data": response.data[0] if response.data else {}}

        return {"success": True, "data": {}}

    except Exception as e:
        logger.error(
            "Failed to update session auth",
            session_id=session_id,
            error=str(e),
        )
        return {"success": False, "error": str(e)}


async def update_session_metadata(
    session_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    referrer: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
) -> dict:
    """
    Update client metadata fields (IP, user-agent, UTM params).
    Typically called once when the session is first created.
    """
    try:
        client = _get_client()

        updates: dict[str, Any] = {}
        if ip_address is not None:
            updates["ip_address"] = ip_address
        if user_agent is not None:
            updates["user_agent"] = user_agent
        if referrer is not None:
            updates["referrer"] = referrer
        if utm_source is not None:
            updates["utm_source"] = utm_source
        if utm_medium is not None:
            updates["utm_medium"] = utm_medium
        if utm_campaign is not None:
            updates["utm_campaign"] = utm_campaign

        if updates:
            response = (
                client.table("user_sessions")
                .update(updates)
                .eq("session_id", session_id)
                .execute()
            )
            return {"success": True, "data": response.data[0] if response.data else {}}

        return {"success": True, "data": {}}

    except Exception as e:
        logger.error(
            "Failed to update session metadata",
            session_id=session_id,
            error=str(e),
        )
        return {"success": False, "error": str(e)}


async def get_user_sessions_by_email(email: str, limit: int = 20) -> dict:
    """Fetch all sessions for a given Google email (for user history)."""
    try:
        client = _get_client()

        response = (
            client.table("user_sessions")
            .select("*")
            .eq("google_email", email)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        return {"success": True, "data": response.data or [], "count": len(response.data or [])}

    except Exception as e:
        logger.error("Failed to fetch sessions by email", email=email, error=str(e))
        return {"success": False, "error": str(e), "data": [], "count": 0}
