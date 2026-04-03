"""
Public plan catalog (prices + feature flags). Admin CRUD can be added later.
"""

from fastapi import APIRouter

from app.models.payment import PlanCatalogRow
from app.services import plan_catalog_service

router = APIRouter()


@router.get("/plans", response_model=list[PlanCatalogRow])
async def list_active_plans():
    rows = await plan_catalog_service.list_active_plans()
    return [
        PlanCatalogRow(
            id=str(r["id"]),
            slug=r["slug"],
            name=r["name"],
            description=r.get("description") or "",
            price_inr=float(r["price_inr"]),
            credits_allocation=r.get("credits_allocation"),
            features=r.get("features") or {},
            display_order=int(r.get("display_order") or 0),
        )
        for r in rows
    ]
