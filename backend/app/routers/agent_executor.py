"""
═══════════════════════════════════════════════════════════════
AGENT EXECUTOR ROUTER — Autonomous Playbook Step Execution
═══════════════════════════════════════════════════════════════
Endpoints:
  POST /api/v1/execute/step   → Execute a single playbook step
"""

import traceback
import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.services import session_store
from app.services.agent_executor_service import execute_playbook_step
from app.services.sheets_connector import create_sheet_from_agent_output

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/execute", tags=["Agent Executor"])


# ── Request / Response Models ──────────────────────────────────

class ExecuteStepRequest(BaseModel):
    session_id: str
    step_number: int             # 1-10
    step_text: str               # full text of the playbook step
    force_type: Optional[str] = None  # "research" | "content" | "outreach" | "strategy"


class ExecuteStepResponse(BaseModel):
    session_id: str
    step_number: int
    step_type: str               # classified type
    output: str                  # agent's output
    sources: list[dict[str, str]] = []   # web sources (research steps only)
    search_queries: list[str] = []
    latency_ms: int
    message: str = ""


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/step", response_model=ExecuteStepResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def execute_step(request: Request, body: ExecuteStepRequest = Body(...)):
    """
    Execute a single playbook step autonomously.

    Classifies the step type (research/content/outreach/strategy)
    then routes to the appropriate specialised agent.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.playbook_agent3_output and not session.playbook_agent1_output:
        raise HTTPException(
            status_code=400,
            detail="Playbook must be generated before executing steps",
        )

    # Build compressed business context from session data
    business_context = _build_business_context(session)
    icp_card = session.playbook_agent2_output or ""

    try:
        result = await execute_playbook_step(
            step_number=body.step_number,
            step_text=body.step_text,
            business_context=business_context,
            icp_card=icp_card,
            force_type=body.force_type,
        )

        logger.info(
            "Step executed successfully",
            session_id=body.session_id,
            step_number=body.step_number,
            step_type=result["step_type"],
            latency_ms=result["latency_ms"],
        )

        return ExecuteStepResponse(
            session_id=body.session_id,
            step_number=result["step_number"],
            step_type=result["step_type"],
            output=result["output"],
            sources=result.get("sources", []),
            search_queries=result.get("search_queries", []),
            latency_ms=result["latency_ms"],
            message=f"Step {body.step_number} executed as {result['step_type']} agent.",
        )

    except Exception as exc:
        logger.error(
            "Step execution failed",
            session_id=body.session_id,
            step_number=body.step_number,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Step execution failed: {str(exc)}")


# ── Export to Google Sheets ────────────────────────────────────

class ExportSheetRequest(BaseModel):
    session_id: str
    step_number: int
    step_type: str
    output: str
    sources: list[dict[str, str]] = []
    search_queries: list[str] = []


class ExportSheetResponse(BaseModel):
    sheet_url: str
    sheet_id: str
    message: str = ""


@router.post("/export-sheet", response_model=ExportSheetResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def export_to_sheet(request: Request, body: ExportSheetRequest = Body(...)):
    """
    Export existing agent output to a Google Sheet.
    Requires GOOGLE_SHEETS_CREDENTIALS_JSON to be configured.
    """
    settings = get_settings()
    if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON:
        raise HTTPException(
            status_code=400,
            detail="Google Sheets credentials not configured. Set GOOGLE_SHEETS_CREDENTIALS_JSON in .env",
        )

    try:
        result = create_sheet_from_agent_output(
            session_id=body.session_id,
            step_number=body.step_number,
            step_type=body.step_type,
            output=body.output,
            sources=body.sources,
            search_queries=body.search_queries,
        )

        logger.info(
            "Exported step to Google Sheets",
            session_id=body.session_id,
            step_number=body.step_number,
            sheet_url=result["sheet_url"],
        )

        return ExportSheetResponse(
            sheet_url=result["sheet_url"],
            sheet_id=result["sheet_id"],
            message=f"Step {body.step_number} exported to Google Sheets.",
        )

    except Exception as exc:
        logger.error(
            "Sheet export failed",
            session_id=body.session_id,
            step_number=body.step_number,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Sheet export failed: {str(exc)}")


# ── Helpers ────────────────────────────────────────────────────

def _build_business_context(session) -> str:
    """
    Build a compressed business context string from session data.
    Uses Agent A output (context brief) if available, else falls back to raw fields.
    """
    if session.playbook_agent1_output:
        # Agent A already contains a well-structured context brief — use it
        return session.playbook_agent1_output[:1500]

    # Fallback: build from raw session fields
    parts = []
    if session.outcome_label:
        parts.append(f"Goal: {session.outcome_label}")
    if session.domain:
        parts.append(f"Domain: {session.domain}")
    if session.task:
        parts.append(f"Task: {session.task}")
    if session.business_profile:
        bp = session.business_profile
        if bp.get("company_name"):
            parts.append(f"Company: {bp['company_name']}")
        if bp.get("industry"):
            parts.append(f"Industry: {bp['industry']}")
        if bp.get("description"):
            parts.append(f"Description: {bp['description'][:300]}")

    return "\n".join(parts) if parts else "No business context available."
