"""
═══════════════════════════════════════════════════════════════
COMPANIES ROUTER — Company Listing & AI-Powered Search
═══════════════════════════════════════════════════════════════
GET  /api/v1/companies          — list companies by domain
POST /api/v1/companies/search   — AI-powered priority search
"""

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Body

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.models.company import (
    CompanyListResponse,
    CompanySearchRequest,
    CompanySearchResponse,
)
from app.services import sheets_service

logger = structlog.get_logger()

router = APIRouter()


@router.get("/companies", response_model=CompanyListResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_COMPANIES)
async def list_companies(
    request: Request,
    domain: str = Query(
        default=None,
        description="Domain slug (e.g., 'social-media', 'legal', 'marketing')",
    ),
):
    """
    Fetch companies from Google Sheets by domain.

    Returns a list of companies with their details (name, problem, description,
    differentiator, AI advantage, funding, pricing).
    """
    result = await sheets_service.fetch_companies_by_domain(domain)

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Failed to fetch companies"),
        )

    return CompanyListResponse(**result)


@router.post("/companies/search", response_model=CompanySearchResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_COMPANIES)
async def search_companies(
    request: Request,
    body: CompanySearchRequest = Body(...),
):
    """
    AI-powered priority search across the company database.

    Uses GPT to intelligently rank and match companies based on the user's
    requirement and context. Falls back to keyword search if no API key.
    """
    user_context = body.userContext.model_dump() if body.userContext else None

    result = await sheets_service.search_companies(
        domain=body.domain,
        subdomain=body.subdomain,
        requirement=body.requirement,
        user_context=user_context,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Company search failed"),
        )

    return CompanySearchResponse(**result)