"""
═══════════════════════════════════════════════════════════════
LEADS ROUTER — Lead Management CRUD
═══════════════════════════════════════════════════════════════
POST  /api/v1/leads              — create lead
PATCH /api/v1/leads/{id}         — update lead
GET   /api/v1/leads              — list leads with filters
POST  /api/v1/leads/{id}/conversations — save conversation
"""



import structlog
from fastapi import APIRouter, Body, HTTPException, Query, Request

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.models.lead import (
    ConversationCreate,
    LeadCreate,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
)
from app.services import supabase_service

logger = structlog.get_logger()

router = APIRouter()


@router.post("/leads", response_model=LeadResponse)
@limiter.limit("20/minute")
async def create_lead(request: Request, body: LeadCreate = Body(...)):
    """
    Create a new lead with server-side scoring.

    The lead score (0–100) is calculated automatically based on
    individual type, tech competency, timeline urgency, and other factors.
    """
    result = await supabase_service.save_lead(body.model_dump())

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save lead"),
        )

    return LeadResponse(**result)


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
@limiter.limit("20/minute")
async def update_lead(request: Request, lead_id: str, body: LeadUpdate = Body(...)):
    """
    Partially update an existing lead.

    If qualification fields are updated, the lead score is automatically
    recalculated.
    """
    updates = body.model_dump(exclude_none=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No fields to update.",
        )

    result = await supabase_service.update_lead(lead_id, updates)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to update lead"),
        )

    return LeadResponse(**result)


@router.get("/leads", response_model=LeadListResponse)
@limiter.limit("30/minute")
async def list_leads(
    request: Request,
    domain: str = Query(default=None, description="Filter by domain"),
    status: str = Query(default=None, description="Filter by status (new, contacted, qualified)"),
    individual_type: str = Query(default=None, description="Filter by individual type"),
    limit: int = Query(default=50, ge=1, le=200, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
):
    """
    Fetch leads with optional filters and pagination.

    Returns leads ordered by creation date (newest first).
    """
    result = await supabase_service.get_leads(
        domain=domain,
        status=status,
        individual_type=individual_type,
        limit=limit,
        offset=offset,
    )

    return LeadListResponse(**result)


@router.post("/leads/{lead_id}/conversations", response_model=LeadResponse)
@limiter.limit("10/minute")
async def save_conversation(
    request: Request,
    lead_id: str,
    body: ConversationCreate,
):
    """
    Store a conversation (messages + recommendations) for a lead.
    """
    result = await supabase_service.save_conversation(
        lead_id=lead_id,
        messages=body.messages,
        recommendations=body.recommendations,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save conversation"),
        )

    return LeadResponse(**result)
