"""
═══════════════════════════════════════════════════════════════
USER SESSION PERSISTENCE — Local PostgreSQL Sync for Session Data
═══════════════════════════════════════════════════════════════
Persists the in-memory SessionContext to the `user_sessions`
table in PostgreSQL after every meaningful state change.

Called from session_store.py on every update_session().
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import structlog

from app.db import get_pool

logger = structlog.get_logger()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {})


def _serialize_qa(session) -> list[dict[str, Any]]:
    return [
        {
            "question": qa.question,
            "answer": qa.answer,
            "question_type": qa.question_type,
        }
        for qa in session.questions_answers
    ]


def _serialize_llm_log(session) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": call.timestamp,
            "service": call.service,
            "model": call.model,
            "purpose": call.purpose,
            "latency_ms": call.latency_ms,
            "token_usage": call.token_usage,
            "error": call.error,
        }
        for call in session.llm_call_log
    ]


def _serialize_final_recommendations(session) -> list[dict[str, Any]]:
    final_recs: list[dict[str, Any]] = []
    for ext in session.recommended_extensions:
        final_recs.append({**ext, "category": "extension"})
    for gpt in session.recommended_gpts:
        final_recs.append({**gpt, "category": "gpt"})
    for comp in session.recommended_companies:
        final_recs.append({**comp, "category": "company"})
    return final_recs


def _session_to_row(session) -> dict[str, Any]:
    """
    Convert an in-memory SessionContext to a dict matching
    the user_sessions table schema.
    """
    return {
        "session_id": session.session_id,
        "updated_at": datetime.utcnow(),
        "stage": session.stage.value if hasattr(session.stage, "value") else str(session.stage),
        "flow_completed": session.stage.value == "complete" if hasattr(session.stage, "value") else False,
        "outcome": session.outcome,
        "outcome_label": session.outcome_label,
        "domain": session.domain,
        "task": session.task,
        "questions_answers": _serialize_qa(session),
        "website_url": session.website_url,
        "gbp_url": session.gbp_url,
        "crawl_summary": session.crawl_summary or {},
        "audience_insights": session.audience_insights or {},
        "business_profile": session.business_profile or {},
        "rca_history": session.rca_history or [],
        "rca_summary": session.rca_summary or None,
        "rca_complete": session.rca_complete,
        "early_recommendations": session.early_recommendations or [],
        "final_recommendations": _serialize_final_recommendations(session),
        "persona_doc_name": session.persona_doc_name,
        "llm_call_log": _serialize_llm_log(session),
    }


def _record_to_dict(record: Any) -> dict[str, Any]:
    if not record:
        return {}
    return dict(record)


def _strip_or_none(value: Optional[str]) -> Optional[str]:
    """Non-empty stripped string, or None (skip column update). Blank must not be sent to UUID/TEXT columns."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


async def upsert_session(session) -> dict:
    """
    Insert or update the user_sessions row for this session.
    """
    try:
        pool = get_pool()
        row = _session_to_row(session)

        async with pool.acquire() as conn:
            saved = await conn.fetchrow(
                """
                INSERT INTO user_sessions (
                    session_id,
                    updated_at,
                    stage,
                    flow_completed,
                    outcome,
                    outcome_label,
                    domain,
                    task,
                    questions_answers,
                    website_url,
                    gbp_url,
                    crawl_summary,
                    audience_insights,
                    business_profile,
                    rca_history,
                    rca_summary,
                    rca_complete,
                    early_recommendations,
                    final_recommendations,
                    persona_doc_name,
                    llm_call_log
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9::jsonb, $10, $11, $12::jsonb, $13::jsonb, $14::jsonb,
                    $15::jsonb, $16, $17, $18::jsonb, $19::jsonb, $20, $21::jsonb
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    stage = EXCLUDED.stage,
                    flow_completed = EXCLUDED.flow_completed,
                    outcome = EXCLUDED.outcome,
                    outcome_label = EXCLUDED.outcome_label,
                    domain = EXCLUDED.domain,
                    task = EXCLUDED.task,
                    questions_answers = EXCLUDED.questions_answers,
                    website_url = EXCLUDED.website_url,
                    gbp_url = EXCLUDED.gbp_url,
                    crawl_summary = EXCLUDED.crawl_summary,
                    audience_insights = EXCLUDED.audience_insights,
                    business_profile = EXCLUDED.business_profile,
                    rca_history = EXCLUDED.rca_history,
                    rca_summary = EXCLUDED.rca_summary,
                    rca_complete = EXCLUDED.rca_complete,
                    early_recommendations = EXCLUDED.early_recommendations,
                    final_recommendations = EXCLUDED.final_recommendations,
                    persona_doc_name = EXCLUDED.persona_doc_name,
                    llm_call_log = EXCLUDED.llm_call_log
                RETURNING *
                """,
                row["session_id"],
                row["updated_at"],
                row["stage"],
                row["flow_completed"],
                row["outcome"],
                row["outcome_label"],
                row["domain"],
                row["task"],
                _json_dumps(row["questions_answers"]),
                row["website_url"],
                row["gbp_url"],
                _json_dumps(row["crawl_summary"]),
                _json_dumps(row["audience_insights"]),
                _json_dumps(row["business_profile"]),
                _json_dumps(row["rca_history"]),
                row["rca_summary"],
                row["rca_complete"],
                _json_dumps(row["early_recommendations"]),
                _json_dumps(row["final_recommendations"]),
                row["persona_doc_name"],
                _json_dumps(row["llm_call_log"]),
            )

        logger.debug(
            "Session persisted to PostgreSQL",
            session_id=session.session_id,
            stage=row["stage"],
        )
        return {"success": True, "data": _record_to_dict(saved)}

    except Exception as e:
        logger.error(
            "Failed to persist session to PostgreSQL",
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
        updates: list[str] = []
        values: list[Any] = []

        def add_update(column: str, value: Any) -> None:
            values.append(value)
            updates.append(f"{column} = ${len(values)}")

        gid = _strip_or_none(google_id) if google_id is not None else None
        if gid is not None:
            add_update("google_id", gid)
        gemail = _strip_or_none(google_email) if google_email is not None else None
        if gemail is not None:
            add_update("google_email", gemail)
        gname = _strip_or_none(google_name) if google_name is not None else None
        if gname is not None:
            add_update("google_name", gname)
        gavatar = _strip_or_none(google_avatar_url) if google_avatar_url is not None else None
        if gavatar is not None:
            add_update("google_avatar_url", gavatar)
        mobile = _strip_or_none(mobile_number) if mobile_number is not None else None
        if mobile is not None:
            add_update("mobile_number", mobile)
        if otp_verified:
            add_update("otp_verified", True)
        ap = _strip_or_none(auth_provider) if auth_provider is not None else None
        if ap is not None:
            add_update("auth_provider", ap)

        if not updates:
            return {"success": True, "data": {}}

        add_update("auth_completed_at", datetime.utcnow())
        add_update("updated_at", datetime.utcnow())
        values.append(session_id)

        pool = get_pool()
        async with pool.acquire() as conn:
            saved = await conn.fetchrow(
                f"""
                UPDATE user_sessions
                SET {", ".join(updates)}
                WHERE session_id = ${len(values)}
                RETURNING *
                """,
                *values,
            )

        logger.info(
            "Session auth updated",
            session_id=session_id,
            auth_provider=auth_provider,
        )
        return {"success": True, "data": _record_to_dict(saved)}

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
        updates: list[str] = []
        values: list[Any] = []

        def add_update(column: str, value: Any) -> None:
            values.append(value)
            updates.append(f"{column} = ${len(values)}")

        if ip_address is not None:
            add_update("ip_address", ip_address)
        if user_agent is not None:
            add_update("user_agent", user_agent)
        if referrer is not None:
            add_update("referrer", referrer)
        if utm_source is not None:
            add_update("utm_source", utm_source)
        if utm_medium is not None:
            add_update("utm_medium", utm_medium)
        if utm_campaign is not None:
            add_update("utm_campaign", utm_campaign)

        if not updates:
            return {"success": True, "data": {}}

        add_update("updated_at", datetime.utcnow())
        values.append(session_id)

        pool = get_pool()
        async with pool.acquire() as conn:
            saved = await conn.fetchrow(
                f"""
                UPDATE user_sessions
                SET {", ".join(updates)}
                WHERE session_id = ${len(values)}
                RETURNING *
                """,
                *values,
            )

        return {"success": True, "data": _record_to_dict(saved)}

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
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM user_sessions
                WHERE google_email = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                email,
                limit,
            )

        data = [_record_to_dict(row) for row in rows]
        return {"success": True, "data": data, "count": len(data)}

    except Exception as e:
        logger.error("Failed to fetch sessions by email", email=email, error=str(e))
        return {"success": False, "error": str(e), "data": [], "count": 0}
