"""
═══════════════════════════════════════════════════════════════
RECOMMENDATIONS ROUTER — Static Data API
═══════════════════════════════════════════════════════════════
GET /api/v1/recommendations/extensions  — Chrome extensions
GET /api/v1/recommendations/gpts        — Custom GPTs
GET /api/v1/recommendations/rca         — RCA questionnaire
GET /api/v1/recommendations/categories  — Available categories
"""



from fastapi import APIRouter, Query, Request

from app.config import get_settings
from app.data.chrome_extensions import CHROME_EXTENSIONS_DATA, get_relevant_extensions
from app.data.custom_gpts import CUSTOM_GPTS_DATA, get_relevant_gpts
from app.data.rca_tree import (
    CATEGORIES_DATA,
    RCA_STAGES,
    find_rca_data,
    get_categories,
)
from app.middleware.rate_limit import limiter

router = APIRouter()


@router.get("/recommendations/extensions")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_extensions(
    request: Request,
    category: str = Query(default="", description="Problem category keyword"),
    goal: str = Query(default="", description="User goal keyword"),
):
    """
    Get Chrome extension recommendations by category.

    If no category is provided, returns all extensions grouped by category.
    """
    if not category and not goal:
        return {"success": True, "data": CHROME_EXTENSIONS_DATA}

    extensions = get_relevant_extensions(category=category, goal=goal)
    return {"success": True, "data": extensions, "count": len(extensions)}


@router.get("/recommendations/gpts")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_gpts(
    request: Request,
    category: str = Query(default="", description="Problem category keyword"),
    goal: str = Query(default="", description="User goal keyword"),
    role: str = Query(default="", description="User role keyword"),
):
    """
    Get Custom GPT recommendations by category, goal, and/or role.

    If no filters are provided, returns all GPTs grouped by category.
    """
    if not category and not goal and not role:
        return {"success": True, "data": CUSTOM_GPTS_DATA}

    gpts = get_relevant_gpts(category=category, goal=goal, role=role)
    return {"success": True, "data": gpts, "count": len(gpts)}


@router.get("/recommendations/rca")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_rca(
    request: Request,
    outcome: str = Query(..., description="Outcome ID (e.g., 'grow-revenue')"),
    persona: str = Query(..., description="Persona ID (e.g., 'founder-owner')"),
    category: str = Query(default="", description="Sub-area category name"),
):
    """
    Get RCA (Root Cause Analysis) questionnaire data.

    If category is provided, returns problem definition questions and
    data collection requirements. Otherwise returns available stages.
    """
    if category:
        rca_data = find_rca_data(outcome=outcome, persona=persona, category=category)
        if not rca_data:
            return {
                "success": False,
                "message": f"No RCA data found for {outcome}/{persona}/{category}",
            }
        return {
            "success": True,
            "data": rca_data,
            "stages": RCA_STAGES,
        }

    return {
        "success": True,
        "stages": RCA_STAGES,
    }


@router.get("/recommendations/categories")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_category_list(
    request: Request,
    outcome: str = Query(..., description="Outcome ID (e.g., 'grow-revenue')"),
    persona: str = Query(..., description="Persona ID (e.g., 'founder-owner')"),
):
    """
    Get available sub-categories for a given outcome and persona.

    Used by the frontend to display the category selection step.
    """
    categories = get_categories(outcome=outcome, persona=persona)
    return {
        "success": True,
        "categories": categories,
        "count": len(categories),
    }
