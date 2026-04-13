from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.middleware.auth_context import require_super_admin
from app.services import products_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("")
async def list_products(active_only: bool = True) -> dict[str, Any]:
    return {"products": await products_service.list_products(active_only=active_only)}


@router.get("/{product_id}")
async def get_product(product_id: str) -> dict[str, Any]:
    product = await products_service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": product}


@router.post("")
async def create_product(req: Request) -> JSONResponse:
    require_super_admin(req)
    body = await req.json()
    try:
        product = await products_service.create_product(body)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "required" in str(exc) else 409, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"product": product})


@router.patch("/{product_id}")
async def patch_product(product_id: str, req: Request) -> dict[str, Any]:
    require_super_admin(req)
    body = await req.json()
    try:
        updated = await products_service.patch_product(product_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": updated}


@router.delete("/{product_id}")
async def delete_product(product_id: str, req: Request) -> JSONResponse:
    require_super_admin(req)
    ok = await products_service.remove_product(product_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Product not found")
    return JSONResponse(status_code=204, content=None)

