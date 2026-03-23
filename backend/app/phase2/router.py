from __future__ import annotations

import asyncio
import json
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .ai import AiHelper
from .agent.final_formatter import format_final_answer
from .agent.orchestrator import RunOpts, run_agent_turn_stream
from .config import CLAUDE_API_KEY, CLAUDE_MODEL, OPENAI_MODEL, STORAGE_BUCKET
from .skills import first_skill_id, get_skill, list_skills, run_skill
from .stores import (
    append_assistant_placeholder,
    append_message,
    create_agent,
    create_plan_run,
    create_skill_call,
    delete_agent,
    delete_conversation,
    ensure_default_agents,
    get_agent,
    get_conversation,
    get_or_create_conversation,
    get_plan_run,
    get_skill_calls_by_message_id,
    get_skill_calls_by_message_id_full,
    get_stage_outputs,
    get_token_usage,
    list_agents,
    save_token_usage,
    list_conversations,
    push_skill_output,
    save_stage_outputs,
    set_skill_call_result,
    update_agent,
    update_message_content,
    update_message_meta,
    update_plan_run,
)

router = APIRouter()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_url_from_message(msg: str) -> str:
    m = re.search(r"https?://\S+", msg or "")
    if not m:
        return ""
    return m.group(0).rstrip("),.;]\"'")


def _get_crawl_pages_excerpt(crawl_data: Any) -> str:
    try:
        pages = crawl_data.get("pages") if isinstance(crawl_data, dict) else None
        if not isinstance(pages, list):
            return ""
        excerpts: list[str] = []
        for p in pages[:6]:
            if not isinstance(p, dict):
                continue
            u = str(p.get("url") or "")
            snap = str(p.get("snapshot") or "")[:1200]
            excerpts.append(f"URL: {u}\nEXCERPT:\n{snap}")
        return "\n\n---\n\n".join(excerpts)
    except Exception:
        return ""


def _normalize_scout_queries(
    scout_data: Any,
    scan_data: Any,
    url: str,
) -> tuple[list[str], str, str, str, str]:
    if not isinstance(scout_data, dict):
        scout_data = {}
    if not isinstance(scan_data, dict):
        scan_data = {}

    result = scout_data.get("result") if isinstance(scout_data.get("result"), dict) else scout_data
    inferred_scope = str(result.get("scope") or scout_data.get("scope") or "")
    covered_region = str(result.get("coveredRegion") or scout_data.get("coveredRegion") or "")
    business_type_guess = str(result.get("businessTypeGuess") or "")
    market_guess = str(
        result.get("marketGuess")
        or scout_data.get("marketGuess")
        or scan_data.get("market")
        or scan_data.get("category")
        or business_type_guess
        or ""
    )
    business_name = str(
        scan_data.get("name") or scan_data.get("businessName") or scan_data.get("brand") or ""
    )
    operation_type = (
        "local" if "local" in inferred_scope.lower()
        else "global" if "global" in inferred_scope.lower()
        else "unknown"
    )

    structured: list[dict[str, Any]] = []
    for q in (result.get("searchQueries") or []):
        if isinstance(q, dict) and q.get("query"):
            structured.append({"query": str(q["query"]).strip(), "priority": q.get("priority", 999)})
    legacy: list[str] = [
        str(q).strip() for q in (result.get("queries") or []) if str(q).strip()
    ]
    raw_queries = (
        [q["query"] for q in sorted(structured, key=lambda x: x["priority"])]
        if structured else legacy
    )

    audience = str(scan_data.get("targetAudience") or scan_data.get("audience") or "").strip()
    region_part = covered_region if operation_type == "local" else ""
    market_core = " ".join(filter(None, [market_guess, audience])).strip() or "business"
    competitor_base = " ".join(filter(None, [market_core, region_part])).strip()
    business_identity = " ".join(filter(None, [business_name, url, region_part])).strip()

    if not raw_queries:
        queries = [
            f"{competitor_base} competitors",
            f"{competitor_base} alternatives",
            f"best {market_core}" + (f" in {region_part}" if region_part else ""),
            f"{business_identity} customer reviews",
            f"{business_identity} listings",
        ]
        return (
            [re.sub(r"\s+", " ", q).strip() for q in queries if q.strip()],
            operation_type, covered_region, market_guess, business_name,
        )

    identity_needle = business_name.lower()
    normalized: list[str] = []
    for q in raw_queries:
        qq = re.sub(r"\s+", " ", q).strip()
        lower = qq.lower()
        if re.search(r"competitor|competitors|alternative|alternatives", lower):
            normalized.append(
                f"{competitor_base} alternatives".strip()
                if re.search(r"alternative|alternatives", lower)
                else f"{competitor_base} competitors".strip()
            )
        elif re.search(
            r"review|reviews|rating|ratings|listing|listings|google maps|zomato|swiggy|justdial|tripadvisor",
            lower,
        ):
            has_identity = bool(identity_needle) and identity_needle in lower
            normalized.append(qq if has_identity else re.sub(r"\s+", " ", f"{business_identity} {qq}").strip())
        else:
            normalized.append(qq)

    seen: set[str] = set()
    deduped = [q for q in normalized if q and not (q in seen or seen.add(q))]  # type: ignore[func-returns-value]
    return deduped, operation_type, covered_region, market_guess, business_name


def _allowed_file_path(path: str) -> bool:
    if ".." in path:
        return False
    allowed = [Path("/tmp").resolve(), Path(STORAGE_BUCKET).resolve()]
    p = Path(path).resolve()
    for root in allowed:
        if p == root or str(p).startswith(str(root) + "/"):
            return True
    return False


async def _resolve_agent_and_skill(payload: dict[str, Any]) -> dict[str, Any]:
    default_skill = first_skill_id() or "platform-scout"

    agent_id = str(payload.get("agentId") or "").strip()
    allowed_from_request = payload.get("allowedSkillIds") if isinstance(payload.get("allowedSkillIds"), list) else []
    allowed_from_request = [str(s) for s in allowed_from_request if isinstance(s, str)]

    if agent_id:
        agent = await get_agent(agent_id)
        if agent:
            allowed = [s for s in agent.get("allowedSkillIds", []) if isinstance(s, str)]
            chosen = next((sid for sid in allowed if get_skill(sid)), default_skill)
            return {
                "agentId": agent_id,
                "skillId": chosen,
                "allowedSkillIds": allowed,
                "contexts": {
                    "skillSelectorContext": agent.get("skillSelectorContext", ""),
                    "finalOutputFormattingContext": agent.get("finalOutputFormattingContext", ""),
                },
            }
        return {"agentId": agent_id, "skillId": default_skill, "allowedSkillIds": allowed_from_request, "contexts": {}}

    first_allowed = next((sid for sid in allowed_from_request if get_skill(sid)), None)
    chosen = first_allowed or default_skill
    return {"agentId": chosen, "skillId": chosen, "allowedSkillIds": allowed_from_request, "contexts": {}}


def _sse(data: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


async def _emit_plan_progress(
    cb,
    message: str,
    *,
    event: str | None = None,
    kind: str = "task",
) -> None:
    if cb is None:
        return
    await cb({
        "stage": "thinking",
        "type": kind,
        "message": message,
        "meta": {"event": event or "info"},
    })


async def _create_plan_draft(
    *,
    body: dict[str, Any],
    emit_progress=None,
) -> dict[str, Any]:
    message = str(body.get("message") or "").strip()
    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(body.get("conversationId"), resolved["agentId"])
    contexts = resolved.get("contexts", {})

    cancel_plan_id = str(body.get("cancelPlanId") or "").strip()
    if cancel_plan_id:
        existing = await get_plan_run(cancel_plan_id)
        if existing and existing.get("conversationId") == conv["id"] and existing.get("status") == "draft":
            await update_plan_run(cancel_plan_id, {"status": "cancelled"})

    user_message_id = await append_message(conv["id"], "user", message)

    placeholder = "\n".join([
        "## Plan (draft)",
        "",
        "- Collect on-site evidence (business-scan + agent browser crawl)",
        "- Run platform-scout (mandatory) to infer scope/region and generate competitor + review queries",
        "- Run web-search (mandatory) using scout queries to find competitor + review URLs",
        "- Execute remaining steps (taxonomy/classify/targeted scraping) after approval",
        "",
        "*(Generating plan...)*",
    ])
    plan_message_id = await append_message(conv["id"], "assistant", placeholder, kind="plan")

    await _emit_plan_progress(emit_progress, "Analyzing request context", event="plan-started")
    url = _extract_url_from_message(message)

    async def _run_skill_for_plan(sid: str, args: dict[str, Any], input_msg: str) -> Any:
        if not get_skill(sid):
            return None
        run_id = f"plan-{plan_message_id}-{sid}-{int(_time.time() * 1000)}"
        skill_call_id = await create_skill_call(conv["id"], plan_message_id, sid, run_id, {"args": args})

        async def _on_prog(event: dict[str, Any]) -> None:
            meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
            await push_skill_output(skill_call_id, {
                "type": "progress",
                "event": str(meta.get("event")) if meta.get("event") else None,
                "payload": meta,
            })

        result = await run_skill(sid, input_msg, history=conv.get("messages") or [], args=args, on_progress=_on_prog)
        await set_skill_call_result(
            skill_call_id,
            "error" if result.status == "error" else "done",
            result.text, result.data, result.error,
        )
        return result

    scan_args: dict[str, Any] = {"url": url} if url else {}
    crawl_args_plan: dict[str, Any] = (
        {"url": url, "maxPages": 5, "maxDepth": 2}
        if url else {}
    )
    crawl_args_execute: dict[str, Any] = (
        {"url": url, "maxPages": 30, "maxDepth": 3} if url else {}
    )

    if url:
        await _emit_plan_progress(emit_progress, "Reading business information from website", event="business-scan-start")
        scan_res, crawl_res = await asyncio.gather(
            _run_skill_for_plan("business-scan", scan_args, message),
            _run_skill_for_plan("scrape-bs4", crawl_args_plan, message),
        )
    else:
        await _emit_plan_progress(
            emit_progress,
            "No URL detected, planning from your prompt context",
            event="no-url",
            kind="info",
        )
        scan_res = crawl_res = None

    scan_text: str = str(scan_res.text) if scan_res and scan_res.text else ""
    scan_data: Any = scan_res.data if scan_res else None
    crawl_data: Any = crawl_res.data if crawl_res else None
    crawl_pages_excerpt = _get_crawl_pages_excerpt(crawl_data)

    scout_input = "\n".join(filter(None, [
        message,
        f"Business URL: {url}" if url else "",
        f"business-scan (text):\n{scan_text}" if scan_text else "",
        f"scrape-bs4 (page excerpts):\n{crawl_pages_excerpt}" if crawl_pages_excerpt else "",
    ]))
    scout_args: dict[str, Any] = {"businessUrl": url, "regionHint": "", "language": ""} if url else {}
    await _emit_plan_progress(emit_progress, "Inferring business scope and discovery queries", event="platform-scout-start")
    scout_res = await _run_skill_for_plan("platform-scout", scout_args, scout_input) if url else None
    scout_data: Any = scout_res.data if scout_res else None

    queries, operation_type, covered_region, market_guess, business_name = _normalize_scout_queries(
        scout_data or {}, scan_data or {}, url
    )
    business_ref = business_name or "business"
    await _emit_plan_progress(
        emit_progress,
        f"Searching {business_ref} related information on web",
        event="web-search-start",
        kind="search",
    )
    web_search_args: dict[str, Any] = {
        "queries": "\n".join(queries),
        "maxResultsPerQuery": 6,
        "maxTotalResults": 40 if queries else 30,
        "region": covered_region,
        "market": market_guess,
        "operationType": operation_type,
        "coveredRegion": covered_region,
        "businessName": business_name,
        "businessUrl": url,
    }
    search_res = await _run_skill_for_plan("web-search", web_search_args, message)
    search_data: Any = search_res.data if search_res else None

    candidate_urls: list[str] = []
    if isinstance(search_data, dict):
        results_list = (
            search_data.get("result", {}).get("results")
            or search_data.get("results")
            or []
        )
        for r in (results_list if isinstance(results_list, list) else []):
            u = r.get("url") or r.get("link") if isinstance(r, dict) else None
            if isinstance(u, str) and u.startswith("http") and u not in candidate_urls:
                candidate_urls.append(u)

    planner_ctx = (contexts.get("skillSelectorContext") or "").strip()
    active_model = CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL

    plan_prompt = "\n".join(filter(None, [
        "You generate an execution plan for a deep business analysis.",
        "",
        "Inputs:",
        "- User request",
        "- On-site evidence (business-scan + crawl excerpts)",
        "- Platform scout output (scope/locality + queries)",
        "- Web search results (candidate URLs)",
        "",
        "Requirements:",
        "- Output MUST be Markdown only.",
        "- Plan must contain a TODO checklist (Markdown checkboxes) that, when completed, guarantees enough evidence to write the final report.",
        "- The checklist must adapt to local vs global scope. If local, include locality/region-specific tasks.",
        "- The plan should be built USING the business context, but should not dump raw scraped data.",
        "- Competitor discovery queries must be market/category + audience + (if local) region based; avoid using only business name for competitor search.",
        "- Review/listing discovery should target exact business identity (name/domain + location for local businesses).",
        '- Include a section titled "Phase 6 — Targeted Collection (Reviews + Competitors)".',
        '- Include a short "Assumptions to verify" section so user can confirm the inferred basics (scope/region/category).',
        '- Add an "Inferred Business Profile" section with: market, operation type (local/global), and region.',
        "",
        f"Planner context:\n{planner_ctx}" if planner_ctx else "",
        "",
        "User request:",
        message,
        "",
        f"Inferred basics (may be wrong): market={market_guess} operationType={operation_type} region={covered_region}",
        "",
        f"business-scan (summary text):\n{scan_text}" if scan_text else "",
        f"crawl excerpts:\n{crawl_pages_excerpt}" if crawl_pages_excerpt else "",
        f"platform-scout (JSON excerpt):\n{json.dumps(scout_data)[:5000]}" if scout_data else "",
        ("web-search candidate URLs:\n" + "\n".join(f"- {u}" for u in candidate_urls[:30])) if candidate_urls else "",
    ]))

    await _emit_plan_progress(emit_progress, "Creating plan draft", event="plan-markdown-generation")
    try:
        ai = AiHelper(temperature=0.2)
        ai_result = await ai.chat(
            message=plan_prompt,
            system_prompt="You are a planning assistant. Output only Markdown. No code fences.",
        )
        plan_markdown = ai_result.message.strip()
        await save_token_usage(plan_message_id, active_model, ai_result.input_tokens, ai_result.output_tokens)
    except Exception:
        plan_markdown = "\n".join([
            "## Execution Plan",
            "",
            f"User request: {message}",
            "",
            "### Checklist",
            "- [ ] Run `business-scan` on target URL/context",
            "- [ ] Run `scrape-bs4` for evidence collection",
            "- [ ] Run `platform-scout` to derive discovery queries",
            "- [ ] Run `web-search` with scout queries",
            "- [ ] Run `platform-taxonomy` and `classify-links`",
            "- [ ] Produce final synthesis",
            "",
            "### Assumptions to verify",
            "- Scope (local/global)",
            "- Region/market",
            "- Primary business category",
        ])

    plan_json = {
        "steps": [
            {"stepId": "scan", "skillId": "business-scan", "args": scan_args, "purpose": "Extract landing page business facts"},
            {"stepId": "crawl", "skillId": "scrape-bs4", "args": crawl_args_execute, "purpose": "Collect multi-page on-site evidence"},
            {"stepId": "scout", "skillId": "platform-scout", "args": scout_args, "dependsOn": ["scan", "crawl"], "purpose": "Generate region-aware review + competitor queries"},
            {"stepId": "search", "skillId": "web-search", "args": web_search_args, "dependsOn": ["scout"], "purpose": "Find review/listing URLs + competitor URLs"},
            {"stepId": "taxonomy", "skillId": "platform-taxonomy", "args": {}, "dependsOn": ["crawl", "search"], "purpose": "Build ecosystem map + domain rules"},
            {"stepId": "classify", "skillId": "classify-links", "args": {}, "dependsOn": ["taxonomy"], "purpose": "Classify discovered URLs"},
        ],
        "evidence": {
            "businessUrl": url,
            "marketGuess": market_guess,
            "operationType": operation_type,
            "coveredRegion": covered_region,
            "scoutQueries": queries,
            "candidateUrls": candidate_urls[:50],
        },
    }

    plan_run = await create_plan_run(conv["id"], user_message_id, plan_message_id, plan_markdown, plan_json)
    await update_message_content(conv["id"], plan_message_id, plan_markdown)
    await update_message_meta(conv["id"], plan_message_id, "plan", plan_run["id"])

    await _emit_plan_progress(emit_progress, "Plan ready for your approval", event="plan-ready", kind="done")
    return {
        "conversationId": conv["id"],
        "planId": plan_run["id"],
        "planMessageId": plan_message_id,
        "planMarkdown": plan_markdown,
        "agentId": resolved["agentId"],
        "skillId": resolved["skillId"],
        "allowedSkillIds": resolved.get("allowedSkillIds", []),
        "contexts": contexts,
    }


def _build_retry_message(
    original_message: str,
    retry_from_stage: str,
    stage_outputs: dict[str, str],
    skill_stages: list[str] | None = None,
) -> str:
    stages = skill_stages or []
    stage_idx = stages.index(retry_from_stage) if retry_from_stage in stages else -1
    if stage_idx <= 0:
        return original_message
    prior_outputs = [
        f"[{stages[i]} output]\n{stage_outputs[stages[i]]}"
        for i in range(stage_idx)
        if stages[i] in stage_outputs and stage_outputs[stages[i]]
    ]
    if not prior_outputs:
        return original_message
    return "\n".join([
        f'RETRY from stage "{retry_from_stage}". Previous stages already completed successfully:',
        "",
        "\n\n".join(prior_outputs),
        "",
        f"Original request: {original_message}",
        "",
        f"Resume from step: {retry_from_stage}. Skip all prior steps.",
    ])


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/api/health")
async def p2_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "ikshan-phase2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": {"provider": "openai", "model": OPENAI_MODEL},
    }


@router.get("/api/skills")
async def p2_skills_root() -> dict[str, Any]:
    return {"skills": list_skills()}


@router.get("/api/chat/skills")
async def p2_skills_chat() -> list[dict[str, Any]]:
    return list_skills()


@router.get("/api/agents")
async def p2_agents_list() -> dict[str, Any]:
    return {"agents": await list_agents()}


@router.post("/api/agents")
async def p2_agents_create(req: Request) -> JSONResponse:
    body = await req.json()
    agent_id = str(body.get("id") or "").strip()
    name = str(body.get("name") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="id is required")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        agent = await create_agent(
            {
                "id": agent_id,
                "name": name,
                "emoji": body.get("emoji") or "🤖",
                "description": body.get("description") or "",
                "allowedSkillIds": body.get("allowedSkillIds") if isinstance(body.get("allowedSkillIds"), list) else [],
                "skillSelectorContext": body.get("skillSelectorContext") or "",
                "finalOutputFormattingContext": body.get("finalOutputFormattingContext") or "",
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(status_code=201, content={"agent": agent})


@router.get("/api/agents/{agent_id}")
async def p2_agents_get(agent_id: str) -> dict[str, Any]:
    agent = await get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": agent}


@router.patch("/api/agents/{agent_id}")
async def p2_agents_patch(agent_id: str, req: Request) -> dict[str, Any]:
    body = await req.json()
    patch: dict[str, Any] = {}
    for key in ["name", "emoji", "description", "allowedSkillIds", "skillSelectorContext", "finalOutputFormattingContext"]:
        if key in body:
            patch[key] = body[key]
    updated = await update_agent(agent_id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent": updated}


@router.delete("/api/agents/{agent_id}")
async def p2_agents_delete(agent_id: str) -> JSONResponse:
    ok = await delete_agent(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return JSONResponse(status_code=204, content=None)


@router.get("/api/files/download")
async def p2_files_download(path: str = Query(...)) -> FileResponse:
    if not _allowed_file_path(path):
        raise HTTPException(status_code=403, detail="Access denied")
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    media = "audio/mpeg" if p.name.endswith(".mp3") else "video/mp4"
    return FileResponse(str(p), media_type=media, filename=p.name)


@router.post("/api/chat/message")
async def p2_chat_message(req: Request) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(body.get("conversationId"), resolved["agentId"])
    await append_message(conv["id"], "user", message)

    result = await run_agent_turn_stream(
        message,
        conv.get("messages") or [],
        resolved["skillId"],
        opts=RunOpts(
            allowed_skill_ids=resolved.get("allowedSkillIds") or None,
            contexts=resolved.get("contexts") or {},
        ),
    )

    text = result.text or ""

    if result.status == "error" and not text:
        try:
            ai = AiHelper(temperature=0.3)
            ai_res = await ai.chat(
                message=message,
                system_prompt="You are a helpful assistant. The skill automation failed. Answer to the best of your ability.",
                conversation_history=conv.get("messages") or [],
            )
            text = ai_res.message.strip() or "I could not run the automation for this request. Please try again or adjust the prompt."
        except Exception:
            text = "I could not run the automation for this request. Please try again or adjust the prompt."

    await append_message(conv["id"], "assistant", text, outputFile=None)
    await save_stage_outputs(conv["id"], {}, None)
    return {
        "message": text,
        "conversationId": conv["id"],
        "runId": result.run_id,
        "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
        "durationMs": result.duration_ms,
        "stageOutputs": {},
        "outputFile": None,
    }


@router.post("/api/chat/stream")
async def p2_chat_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    retry_from_stage = str(body.get("retryFromStage") or "").strip()
    retry_stage_outputs: dict[str, str] = body.get("stageOutputs") or {}
    if retry_from_stage and isinstance(retry_stage_outputs, dict):
        message = _build_retry_message(message, retry_from_stage, retry_stage_outputs)

    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(body.get("conversationId"), resolved["agentId"])

    await append_message(conv["id"], "user", message)
    assistant_message_id = await append_assistant_placeholder(conv["id"])

    merged_stage_outputs = await get_stage_outputs(conv["id"])

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                tokens_emitted = 0

                async def on_stage(stage: str, label: str, idx: int) -> None:
                    await emit({"stage": stage, "label": label, "stageIndex": idx, "agentId": resolved["agentId"]})

                async def on_token(token: str) -> None:
                    nonlocal tokens_emitted
                    await emit({"token": token})
                    tokens_emitted += len(token)

                await emit({"stage": "thinking", "label": "Thinking", "stageIndex": 0, "agentId": resolved["agentId"]})

                result = await run_agent_turn_stream(
                    message,
                    conv.get("messages") or [],
                    resolved["skillId"],
                    on_stage=on_stage,
                    on_token=on_token,
                    on_progress=emit_progress,
                    opts=RunOpts(
                        allowed_skill_ids=resolved.get("allowedSkillIds") or None,
                        contexts=resolved.get("contexts") or {},
                        conversation_id=conv["id"],
                        message_id=assistant_message_id,
                    ),
                )

                text = result.text or ""
                if result.status == "error" and not text:
                    text = "I could not run the automation for this request. Please try again."

                if text and tokens_emitted == 0:
                    await emit({"token": text})
                elif result.status == "error" and tokens_emitted == 0:
                    await emit({"token": text})

                skills_count = len(await get_skill_calls_by_message_id(assistant_message_id))
                await update_message_content(conv["id"], assistant_message_id, text, None, skills_count)
                await save_stage_outputs(conv["id"], merged_stage_outputs, None)

                token_usage = await get_token_usage(assistant_message_id)
                await emit(
                    {
                        "done": True,
                        "conversationId": conv["id"],
                        "messageId": assistant_message_id,
                        "runId": result.run_id,
                        "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
                        "durationMs": result.duration_ms,
                        "stageOutputs": merged_stage_outputs,
                        "outputFile": None,
                        "agentId": resolved["agentId"],
                        "tokenUsage": token_usage,
                    }
                )
            except Exception as exc:
                await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/api/chat/plan")
async def p2_chat_plan(req: Request) -> dict[str, Any]:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    return await _create_plan_draft(body=body)


@router.post("/api/chat/plan/stream")
async def p2_chat_plan_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                await emit({"stage": "thinking", "label": "Building plan", "stageIndex": 0})
                result = await _create_plan_draft(body=body, emit_progress=emit_progress)
                await emit({
                    "done": True,
                    "conversationId": result.get("conversationId"),
                    "planId": result.get("planId"),
                    "planMessageId": result.get("planMessageId"),
                    "planMarkdown": result.get("planMarkdown"),
                    "agentId": result.get("agentId"),
                    "skillId": result.get("skillId"),
                })
            except Exception as exc:
                await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.post("/api/chat/plan/approve/stream")
async def p2_approve_plan_stream(req: Request) -> StreamingResponse:
    body = await req.json()
    plan_id = str(body.get("planId") or "").strip()
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required")

    resolved = await _resolve_agent_and_skill(body)
    conv = await get_or_create_conversation(body.get("conversationId"), resolved["agentId"])

    plan = await get_plan_run(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    if plan.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="plan was cancelled (create a new plan)")
    if plan.get("status") in ("executing", "done"):
        raise HTTPException(status_code=409, detail=f"plan is already {plan.get('status')}")

    if isinstance(body.get("planMarkdown"), str) and body.get("planMarkdown").strip():
        await update_plan_run(plan_id, {"planMarkdown": body.get("planMarkdown")})
    await update_plan_run(plan_id, {"status": "approved"})

    assistant_message_id = await append_assistant_placeholder(conv["id"])

    async def generator():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        done = asyncio.Event()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(_sse(event))

        async def emit_progress(event: dict[str, Any]) -> None:
            await emit({"progress": event})

        async def worker() -> None:
            try:
                exec_start_ms = _time.time() * 1000
                tokens_emitted = 0
                await update_plan_run(plan_id, {"status": "executing"})
                await emit({"stage": "thinking", "label": "Executing plan", "stageIndex": 0, "agentId": resolved["agentId"]})

                steps = plan.get("planJson", {}).get("steps", []) if isinstance(plan.get("planJson"), dict) else []
                user_message = ""
                for msg in reversed(conv.get("messages") or []):
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        candidate = str(msg.get("content") or "").strip()
                        if candidate:
                            user_message = candidate
                            break
                stage_outputs: dict[str, str] = {}
                step_results: dict[str, Any] = {}

                for idx, step in enumerate(steps):
                    if not isinstance(step, dict):
                        continue
                    sid = str(step.get("skillId") or "").strip()
                    step_id = str(step.get("stepId") or f"step-{idx + 1}")
                    if not sid:
                        continue
                    if resolved.get("allowedSkillIds") and sid not in (resolved.get("allowedSkillIds") or []):
                        continue

                    step_args: dict[str, Any] = dict(step.get("args") or {})
                    if sid == "web-search":
                        scout = (step_results.get("scout") or {}).get("data") or {}
                        result_block = scout.get("result") or scout
                        structured_qs = [
                            str(q.get("query", "")).strip()
                            for q in (result_block.get("searchQueries") or [])
                            if isinstance(q, dict) and q.get("query")
                        ]
                        legacy_qs = [
                            str(q).strip()
                            for q in (result_block.get("queries") or [])
                            if str(q).strip()
                        ]
                        chosen_qs = structured_qs if structured_qs else legacy_qs
                        if chosen_qs and (not step_args.get("queries") or "(from platform-scout" in str(step_args.get("queries"))):
                            step_args["queries"] = "\n".join(chosen_qs)
                        scope = str(result_block.get("scope") or "").strip().lower()
                        step_args.setdefault("market", str(result_block.get("marketGuess") or ""))
                        step_args.setdefault("businessType", str(result_block.get("businessTypeGuess") or ""))
                        step_args.setdefault("operationType", scope if scope in ("local", "global") else "")
                        step_args.setdefault("coveredRegion", str(result_block.get("coveredRegion") or ""))

                    await emit({"stage": "running", "label": f"Running {sid}", "stageIndex": idx + 1, "agentId": resolved["agentId"]})

                    run_id = f"run-{sid}-{idx}-{uuid4().hex[:8]}"
                    call_id = await create_skill_call(conv["id"], assistant_message_id, sid, run_id, {"args": step_args})

                    async def on_progress(event: dict[str, Any]) -> None:
                        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
                        await push_skill_output(
                            call_id,
                            {"type": "progress", "event": str(meta.get("event")) if meta.get("event") else None, "payload": meta},
                        )
                        await emit_progress(event)

                    result = await run_skill(
                        sid,
                        plan.get("planMarkdown") or "",
                        history=conv.get("messages") or [],
                        args=step_args,
                        on_progress=on_progress,
                    )
                    step_results[step_id] = {"text": result.text, "data": result.data}

                    await set_skill_call_result(call_id, "error" if result.status == "error" else "done", result.text, result.data, result.error)

                    if result.text:
                        stage_outputs[sid] = result.text

                formatter_calls = await get_skill_calls_by_message_id(assistant_message_id)
                async def _on_final_token(token: str) -> None:
                    nonlocal tokens_emitted
                    tokens_emitted += len(token)
                    await emit({"token": token})
                fmt = await format_final_answer(
                    message=user_message or (plan.get("planMarkdown") or ""),
                    start_ms=exec_start_ms,
                    skill_calls=formatter_calls,
                    last_skill_result=None,
                    contexts=resolved.get("contexts") or {},
                    on_token=_on_final_token,
                )
                final_text = (fmt.text or "").strip()
                if final_text and tokens_emitted == 0:
                    await emit({"token": final_text})

                skills_count = len(await get_skill_calls_by_message_id(assistant_message_id))
                await update_message_content(conv["id"], assistant_message_id, final_text, None, skills_count)
                await save_stage_outputs(conv["id"], stage_outputs, None)

                await update_plan_run(plan_id, {"status": "done"})
                token_usage = await get_token_usage(assistant_message_id)
                await emit(
                    {
                        "done": True,
                        "conversationId": conv["id"],
                        "messageId": assistant_message_id,
                        "runId": fmt.run_id,
                        "model": CLAUDE_MODEL if CLAUDE_API_KEY else OPENAI_MODEL,
                        "durationMs": fmt.duration_ms,
                        "stageOutputs": stage_outputs,
                        "outputFile": None,
                        "agentId": resolved["agentId"],
                        "tokenUsage": token_usage,
                    }
                )
            except Exception as exc:
                await update_plan_run(plan_id, {"status": "error"})
                await emit({"stage": "error", "label": "Error", "stageIndex": -1, "error": str(exc)})
            finally:
                done.set()

        asyncio.create_task(worker())

        while not done.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
                yield chunk
            except asyncio.TimeoutError:
                yield b": ping\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/api/chat/messages")
async def p2_chat_messages(conversationId: str | None = None) -> dict[str, Any]:
    conv = await get_or_create_conversation(conversationId)
    return {
        "messages": conv.get("messages") or [],
        "conversationId": conv["id"],
        "agentId": conv.get("agentId"),
        "lastStageOutputs": conv.get("lastStageOutputs") or {},
        "lastOutputFile": conv.get("lastOutputFile"),
    }


@router.get("/api/chat/skill-calls")
async def p2_chat_skill_calls(messageId: str | None = None) -> dict[str, Any]:
    if not messageId or not messageId.strip():
        raise HTTPException(status_code=400, detail="messageId is required")
    return {"skillCalls": await get_skill_calls_by_message_id_full(messageId.strip())}


@router.get("/api/chat/token-usage")
async def p2_chat_token_usage(messageId: str | None = None) -> dict[str, Any]:
    if not messageId or not messageId.strip():
        raise HTTPException(status_code=400, detail="messageId is required")
    return await get_token_usage(messageId.strip())


@router.get("/api/chat/conversations")
async def p2_chat_conversations() -> dict[str, Any]:
    return {"conversations": await list_conversations()}


@router.delete("/api/chat/conversations/{conversation_id}")
async def p2_chat_delete_conversation(conversation_id: str) -> dict[str, bool]:
    return {"ok": await delete_conversation(conversation_id)}
