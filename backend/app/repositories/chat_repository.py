from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from app.db import get_pool
from app.doable_claw_agent.stores import (
    delete_conversation,
    get_or_create_conversation,
    get_skill_calls_by_message_id_full,
    get_token_usage,
    list_conversations,
    now_iso,
)
from app.repositories import onboarding_repository as onboarding_repo
from app.repositories import playbook_runs_repository as playbook_repo
from app.repositories import task_stream_repository as task_stream_repo
from app.skills.service import list_skills
from app.services.journey_service import (
    JOURNEY_STEP_OUTCOME,
    JOURNEY_STEP_DOMAIN,
    JOURNEY_STEP_TASK,
    JOURNEY_STEP_URL,
    JOURNEY_STEP_SCALE,
    JOURNEY_STEP_DIAGNOSTIC,
    JOURNEY_STEP_PRECISION,
    JOURNEY_STEP_GAP,
    JOURNEY_STEP_PLAYBOOK,
    get_outcome_options,
    get_domain_options,
    get_task_options,
    get_scale_question_by_id,
)


def _extract_company_name(website_url: str) -> str:
    raw = str(website_url or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        host = (urlparse(candidate).hostname or "").lower().strip(".")
    except Exception:
        return ""
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    base = host.split(".")[0].replace("-", " ").replace("_", " ").strip()
    if not base:
        return ""
    return " ".join(part.capitalize() for part in base.split())


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _has_onboarding_markers(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        step = str(msg.get("journeyStep") or "")
        mid = str(msg.get("messageId") or "")
        if step in (JOURNEY_STEP_OUTCOME, JOURNEY_STEP_DOMAIN, JOURNEY_STEP_TASK,
                    JOURNEY_STEP_URL, JOURNEY_STEP_SCALE, JOURNEY_STEP_DIAGNOSTIC,
                    JOURNEY_STEP_PRECISION, JOURNEY_STEP_GAP, JOURNEY_STEP_PLAYBOOK):
            return True
        if mid.startswith("onboarding:"):
            return True
    return False


async def _attach_onboarding_transcript(
    messages: list[dict[str, Any]],
    *,
    onboarding_session_id: str | None,
) -> list[dict[str, Any]]:
    """
    Convert onboarding table row into messages matching the business_problem_identifier
    journey flow format. Messages include:
    - Outcome question + answer
    - Domain question + answer
    - Task question + answer
    - URL question + answer
    - Scale questions + answers
    - Diagnostic (RCA) questions + answers
    - Precision questions + answers
    - Gap questions + answers
    """
    sid = str(onboarding_session_id or "").strip()
    if not sid:
        return messages
    if _has_onboarding_markers(messages):
        return messages

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_transcript_fields(conn, sid)

    if not row:
        return messages

    outcome = str(row.get("outcome") or "").strip()
    domain = str(row.get("domain") or "").strip()
    task = str(row.get("task") or "").strip()
    website_url = str(row.get("website_url") or "").strip()
    scale_answers = _as_dict(row.get("scale_answers"))
    rca_qa = _as_list(row.get("rca_qa"))
    precision_questions = _as_list(row.get("precision_questions"))
    precision_answers = _as_list(row.get("precision_answers"))
    gap_questions = _as_list(row.get("gap_questions"))
    gap_answers_raw = str(row.get("gap_answers") or "").strip()

    # Parse gap_answers (can be JSON dict like {"Q1": "A", "Q2": "B"})
    gap_answers_map: dict[str, str] = {}
    if gap_answers_raw:
        try:
            parsed = json.loads(gap_answers_raw)
            if isinstance(parsed, dict):
                gap_answers_map = {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            pass

    onboarding_msgs: list[dict[str, Any]] = []
    created_at = now_iso()
    acc: dict[str, Any] = {"onboardingSessionId": sid}

    # ── Outcome Q&A ──
    if outcome:
        # Map outcome id to label
        outcome_labels = {
            "lead-generation": "Lead Generation",
            "sales-retention": "Sales & Retention",
            "business-strategy": "Business Strategy",
            "save-time": "Save Time",
        }
        outcome_text = outcome_labels.get(outcome, outcome)

        onboarding_msgs.append({
            "role": "assistant",
            "content": "What outcome are you looking to achieve?",
            "options": get_outcome_options(),
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_OUTCOME,
            "journeySelections": acc,
            "kind": "final",
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:outcome:q",
        })
        onboarding_msgs.append({
            "role": "user",
            "content": outcome_text,
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:outcome:a",
        })
        acc["outcome"] = outcome

    # ── Domain Q&A ──
    if domain:
        domain_options = get_domain_options(outcome) if outcome else None
        onboarding_msgs.append({
            "role": "assistant",
            "content": "Which domain applies to your business?",
            "options": domain_options or [],
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_DOMAIN,
            "journeySelections": acc,
            "kind": "final",
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:domain:q",
        })
        onboarding_msgs.append({
            "role": "user",
            "content": domain,
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:domain:a",
        })
        acc["domain"] = domain

    # ── Task Q&A ──
    if task:
        task_options = get_task_options(domain) if domain else None
        onboarding_msgs.append({
            "role": "assistant",
            "content": "What's the specific task or challenge you want to address?",
            "options": task_options or [],
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_TASK,
            "journeySelections": acc,
            "kind": "final",
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:task:q",
        })
        onboarding_msgs.append({
            "role": "user",
            "content": task,
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:task:a",
        })
        acc["task"] = task

    # ── URL Q&A ──
    if website_url:
        onboarding_msgs.append({
            "role": "assistant",
            "content": "What's your website URL? (or type 'Skip' to continue without one)",
            "options": ["Skip"],
            "allowCustomAnswer": True,
            "journeyStep": JOURNEY_STEP_URL,
            "journeySelections": acc,
            "kind": "final",
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:url:q",
        })
        onboarding_msgs.append({
            "role": "user",
            "content": website_url,
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:url:a",
        })
        acc["websiteUrl"] = website_url

    # ── Scale Questions Q&A ──
    if scale_answers:
        for q_id, answer in scale_answers.items():
            answer_text = ", ".join(answer) if isinstance(answer, list) else str(answer)

            # Get the actual question from scale_questions.json
            scale_q = get_scale_question_by_id(q_id)
            if scale_q:
                question_text = f"**{scale_q.get('question', q_id)}**"
                options = scale_q.get("options") or []
            else:
                question_text = f"**{q_id}**"
                options = []

            onboarding_msgs.append({
                "role": "assistant",
                "content": question_text,
                "options": options,
                "allowCustomAnswer": False,
                "journeyStep": JOURNEY_STEP_SCALE,
                "journeySelections": {**acc, "scaleAnswers": scale_answers},
                "kind": "final",
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:scale:{q_id}:q",
            })
            onboarding_msgs.append({
                "role": "user",
                "content": answer_text,
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:scale:{q_id}:a",
            })
        acc["scaleAnswers"] = scale_answers

    # ── Diagnostic (RCA) Q&A ──
    for idx, item in enumerate(rca_qa):
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        options = item.get("options") or []

        if question:
            onboarding_msgs.append({
                "role": "assistant",
                "content": question,
                "options": options,
                "allowCustomAnswer": True,
                "journeyStep": JOURNEY_STEP_DIAGNOSTIC,
                "journeySelections": acc,
                "kind": "final",
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:diagnostic:{idx}:q",
            })
        if answer:
            onboarding_msgs.append({
                "role": "user",
                "content": answer,
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:diagnostic:{idx}:a",
            })

    # ── Precision Q&A ──
    for idx, pq in enumerate(precision_questions):
        question = str(pq.get("question") or "").strip()
        options = pq.get("options") or []

        # Find matching answer
        answer = ""
        for pa in precision_answers:
            if pa.get("question_index") == idx:
                answer = str(pa.get("answer") or "").strip()
                break

        if question:
            onboarding_msgs.append({
                "role": "assistant",
                "content": question,
                "options": options,
                "allowCustomAnswer": True,
                "journeyStep": JOURNEY_STEP_PRECISION,
                "journeySelections": acc,
                "kind": "final",
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:precision:{idx}:q",
            })
        if answer:
            onboarding_msgs.append({
                "role": "user",
                "content": answer,
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:precision:{idx}:a",
            })

    # ── Gap Q&A ──
    for idx, gq in enumerate(gap_questions):
        question = str(gq.get("question") or "").strip()
        options = gq.get("options") or []
        q_id = str(gq.get("id") or f"Q{idx+1}")

        # Find matching answer from gap_answers_map
        answer = gap_answers_map.get(q_id, "")
        # Also try by index
        if not answer:
            for opt in options:
                if opt.startswith(f"{answer})"):
                    break

        if question:
            onboarding_msgs.append({
                "role": "assistant",
                "content": question,
                "options": options,
                "allowCustomAnswer": True,
                "journeyStep": JOURNEY_STEP_GAP,
                "journeySelections": acc,
                "kind": "final",
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:gap:{idx}:q",
            })
        if answer:
            # Convert answer key to full option text if possible
            answer_text = answer
            for opt in options:
                if opt.startswith(f"{answer})"):
                    answer_text = opt
                    break
            onboarding_msgs.append({
                "role": "user",
                "content": answer_text,
                "createdAt": created_at,
                "messageId": f"onboarding:{sid}:gap:{idx}:a",
            })

    # ── Playbook Placeholder ──
    # Add the playbook placeholder message so _attach_playbook_content can attach
    # the actual playbook content. This is needed because onboarding-based conversations
    # don't have stored messages with the journeyStep == "playbook".
    if outcome or domain or task:  # Only add if onboarding has some data
        onboarding_msgs.append({
            "role": "assistant",
            "content": (
                "Generating your personalised playbook — this may take a moment. "
                "I'll show it here as soon as it's ready."
            ),
            "options": [],
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_PLAYBOOK,
            "journeySelections": acc,
            "kind": "final",
            "createdAt": created_at,
            "messageId": f"onboarding:{sid}:playbook:placeholder",
        })

    return onboarding_msgs + messages


async def _attach_playbook_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Post-processor: if there's a playbook placeholder message (journeyStep == "playbook"),
    either:
    1. Attach the completed playbook content if available
    2. Add stream status info (streamId, canRetry) so UI can show progress or retry button

    Lookup strategy for playbook:
    1. First try playbook_runs.session_id = onboarding_id (legacy/compatible)
    2. Fallback: via onboarding.playbook_run_id FK
    """
    if not messages:
        return messages

    # Find the playbook placeholder message (scan from end)
    playbook_msg_idx: int | None = None
    onboarding_id: str = ""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if (
            msg.get("role") == "assistant"
            and msg.get("journeyStep") == "playbook"
        ):
            selections = msg.get("journeySelections") or {}
            sid = str(selections.get("onboardingSessionId") or "").strip()
            if sid:
                playbook_msg_idx = i
                onboarding_id = sid
            break

    if playbook_msg_idx is None or not onboarding_id:
        return messages

    # Check if playbook content already exists as a subsequent message
    for j in range(playbook_msg_idx + 1, len(messages)):
        subsequent = messages[j]
        if (
            subsequent.get("role") == "assistant"
            and subsequent.get("journeyStep") == "playbook_content"
        ):
            # Already attached in a prior call or stored — nothing to do
            return messages

    # Look up completed playbook from playbook_runs
    # Strategy 1: session_id = onboarding_id (most playbooks use this)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await playbook_repo.find_latest_complete_by_session(conn, onboarding_id)
        # Strategy 2: If not found via session_id, try via onboarding.playbook_run_id FK
        if not row or row["status"] != "complete":
            row = await playbook_repo.find_latest_via_onboarding_fk(conn, onboarding_id)

    # If playbook is complete, inject it as a message
    if row and row["status"] == "complete":
        playbook_text = str(row["playbook"] or "").strip()
        if playbook_text:
            # Build the playbookData object matching the frontend PlaybookData interface
            playbook_data: dict[str, str] = {
                "playbook": playbook_text,
                "websiteAudit": str(row["website_audit"] or "").strip(),
                "contextBrief": str(row["context_brief"] or "").strip(),
                "icpCard": str(row["icp_card"] or "").strip(),
            }

            # Extract websiteUrl from the placeholder message's journeySelections
            placeholder_selections = messages[playbook_msg_idx].get("journeySelections") or {}
            website_url = str(placeholder_selections.get("websiteUrl") or "").strip()

            # Build cross-agent actions (e.g. "Do Deep Analysis" → research-orchestrator)
            cross_agent_actions: list[dict[str, str]] = []
            if website_url:
                cross_agent_actions.append({
                    "label": "Do Deep Analysis",
                    "icon": "🔬",
                    "agentId": "research-orchestrator",
                    "initialMessage": f"Do deep analysis of {website_url}",
                })

            # Inject the playbook as an additional assistant message right after the placeholder
            playbook_content_msg: dict[str, Any] = {
                "role": "assistant",
                "content": playbook_text,
                "createdAt": now_iso(),
                "journeyStep": "playbook_content",
                "playbookData": playbook_data,
            }
            if cross_agent_actions:
                playbook_content_msg["crossAgentActions"] = cross_agent_actions

            result = list(messages)
            result.insert(playbook_msg_idx + 1, playbook_content_msg)
            return result

    # Playbook not complete — check task stream status for retry/resume info
    result = list(messages)
    async with pool.acquire() as conn:
        stream_row = await task_stream_repo.find_latest_by_session_and_type(
            conn, onboarding_id, "playbook/onboarding-generate"
        )

    # Update the placeholder message with stream status
    placeholder = result[playbook_msg_idx]
    if stream_row:
        stream_id = str(stream_row["stream_id"] or "")
        stream_status = str(stream_row["status"] or "")

        placeholder["streamId"] = stream_id
        placeholder["streamStatus"] = stream_status
        # Also put streamId in journeySelections for frontend compatibility
        if "journeySelections" in placeholder:
            placeholder["journeySelections"]["streamId"] = stream_id

        # If stream is in error/cancelled state, allow retry
        if stream_status in ("error", "cancelled", "failed"):
            placeholder["canRetry"] = True
            placeholder["options"] = ["Retry Playbook"]
            placeholder["content"] = (
                "⚠️ Playbook generation failed. Click **Retry Playbook** to try again."
            )
        elif stream_status == "running":
            placeholder["canRetry"] = False
            # Keep the generating message
        elif stream_status == "complete":
            # Stream completed but playbook not in playbook_runs yet — might be race condition
            placeholder["canRetry"] = False
    else:
        # No stream found — allow retry to start fresh
        placeholder["canRetry"] = True
        placeholder["options"] = ["Retry Playbook"]
        placeholder["content"] = (
            "⚠️ Playbook generation hasn't started. Click **Retry Playbook** to generate your playbook."
        )

    return result


async def get_messages(
    conversation_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    conv = await get_or_create_conversation(
        conversation_id,
        onboarding_id=session_id,
        user_id=user_id,
    )

    messages = conv.get("messages") or []
    onboarding_sid = str(conv.get("onboardingId") or session_id or "").strip() or None
    messages = await _attach_onboarding_transcript(messages, onboarding_session_id=onboarding_sid)
    messages = await _attach_playbook_content(messages)
    return {
        "messages": messages,
        "conversationId": conv["id"],
        "agentId": conv.get("agentId"),
        "lastStageOutputs": conv.get("lastStageOutputs") or {},
        "lastOutputFile": conv.get("lastOutputFile"),
    }


async def get_conversations(
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "conversations": await list_conversations(
            session_id=session_id,
            user_id=user_id,
        )
    }


async def get_playbook_history(
    user_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    page_size = max(1, min(int(limit or 20), 100))
    page_offset = max(0, int(offset or 0))

    if uid is None or uid == "":
        return {
            "playbooks": [],
            "pagination": {
                "limit": limit,
                "offset": page_offset,
                "total": 0,
                "hasMore": False,
            },
        }

    pool = get_pool()
    async with pool.acquire() as conn:
        all_session_rows = await playbook_repo.find_distinct_sessions_by_user(conn, uid)
        total = len(all_session_rows)
        rows = await playbook_repo.find_paginated_by_user(conn, uid, max(200, page_size + page_offset + 50))

    # One row per onboarding journey (`session_id` == onboarding.id): latest complete playbook only.
    seen_sessions: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        run_session_id = str(data.get("session_id") or "").strip()
        if not run_session_id or run_session_id in seen_sessions:
            continue
        seen_sessions.add(run_session_id)

        snapshot = data.get("onboarding_snapshot")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except Exception:
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        outcome = str(snapshot.get("outcome") or "").strip()
        domain = str(snapshot.get("domain") or "").strip()
        task = str(snapshot.get("task") or "").strip()
        website_url = str(snapshot.get("website_url") or "").strip()
        company_name = _extract_company_name(website_url)
        title = company_name or task or domain or outcome or "Generated playbook"

        items.append(
            {
                "runId": str(data.get("id") or ""),
                "sessionId": run_session_id,
                "title": title,
                "companyName": company_name,
                "outcome": outcome,
                "domain": domain,
                "task": task,
                "updatedAt": data.get("updated_at"),
                "createdAt": data.get("created_at"),
            }
        )

    paged_items = items[page_offset: page_offset + page_size]
    has_more = (page_offset + len(paged_items)) < total
    return {
        "playbooks": paged_items,
        "pagination": {
            "limit": page_size,
            "offset": page_offset,
            "total": total,
            "hasMore": has_more,
        },
    }


async def get_playbook_run_for_user(run_id: str, user_id: str) -> dict[str, Any] | None:
    """Return one completed playbook row if it belongs to the authenticated user."""
    rid = str(run_id or "").strip()
    uid = str(user_id or "").strip()
    if not rid or not uid:
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await playbook_repo.find_by_id_and_user(conn, rid, uid)

    if not row:
        return None

    data = dict(row)
    playbook_text = str(data.get("playbook") or "").strip()
    if not playbook_text:
        return None

    snapshot = data.get("onboarding_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    outcome = str(snapshot.get("outcome") or "").strip()
    domain = str(snapshot.get("domain") or "").strip()
    task = str(snapshot.get("task") or "").strip()
    website_url = str(snapshot.get("website_url") or "").strip()
    title = task or domain or outcome or "Generated playbook"

    playbook_data: dict[str, str] = {
        "playbook": playbook_text,
        "websiteAudit": str(data.get("website_audit") or "").strip(),
        "contextBrief": str(data.get("context_brief") or "").strip(),
        "icpCard": str(data.get("icp_card") or "").strip(),
    }

    cross_agent_actions: list[dict[str, str]] = []
    if website_url:
        cross_agent_actions.append(
            {
                "label": "Do Deep Analysis",
                "icon": "🔬",
                "agentId": "research-orchestrator",
                "initialMessage": f"Do deep analysis of {website_url}",
            }
        )

    return {
        "runId": str(data.get("id") or ""),
        "sessionId": str(data.get("session_id") or ""),
        "title": title,
        "outcome": outcome,
        "domain": domain,
        "task": task,
        "playbookData": playbook_data,
        "crossAgentActions": cross_agent_actions,
    }


async def get_skills() -> list[dict[str, Any]]:
    return list_skills()


async def get_skill_calls(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return {"skillCalls": await get_skill_calls_by_message_id_full(message_id.strip())}


async def get_token_usage_by_message(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return await get_token_usage(message_id.strip())


async def delete_conversation_by_id(conversation_id: str) -> dict[str, bool]:
    return {"ok": await delete_conversation(conversation_id)}

