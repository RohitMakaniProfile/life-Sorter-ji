from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.middleware.auth_context import require_super_admin
from app.services import agents_service

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.get("")
async def agents_list() -> dict[str, Any]:
    return {"agents": await agents_service.get_agents_list()}


@router.post("")
async def agents_create(req: Request) -> JSONResponse:
    require_super_admin(req)
    body = await req.json()
    try:
        agent = await agents_service.create_new_agent(body)
    except ValueError as exc:
        raise HTTPException(status_code=400 if "required" in str(exc) else 409, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"agent": agent})


@router.get("/{agent_id}")
async def agents_get(agent_id: str) -> dict[str, Any]:
    agent = await agents_service.get_agent_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": agent}


@router.patch("/{agent_id}")
async def agents_patch(agent_id: str, req: Request) -> dict[str, Any]:
    require_super_admin(req)
    body = await req.json()
    updated = await agents_service.patch_agent(agent_id, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": updated}


@router.delete("/{agent_id}")
async def agents_delete(agent_id: str, req: Request) -> JSONResponse:
    require_super_admin(req)
    ok = await agents_service.remove_agent(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return JSONResponse(status_code=204, content=None)