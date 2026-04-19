from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

_DATA_PATH = Path(__file__).parent.parent / "data" / "business_problem_journey.json"
_SCALE_PATH = Path(__file__).parent.parent / "data" / "scale_questions.json"

with _DATA_PATH.open() as _f:
    _JOURNEY: dict[str, Any] = json.load(_f)

with _SCALE_PATH.open() as _f:
    _SCALE_QUESTIONS: list[dict[str, Any]] = json.load(_f)

# outcome text → outcome id (e.g. "Lead Generation" → "lead-generation")
_OUTCOME_TEXT_TO_ID: dict[str, str] = {
    o["text"]: o["id"] for o in _JOURNEY["outcomes"]
}

_OUTCOME_LABEL: dict[str, str] = {
    "lead-generation": "Lead Generation",
    "sales-retention": "Sales & Retention",
    "business-strategy": "Business Strategy",
    "save-time": "Save Time",
}

JOURNEY_STEP_OUTCOME    = "outcome"
JOURNEY_STEP_DOMAIN     = "domain"
JOURNEY_STEP_TASK       = "task"
JOURNEY_STEP_URL        = "url"
JOURNEY_STEP_SCALE      = "scale"
JOURNEY_STEP_DIAGNOSTIC = "diagnostic"
JOURNEY_STEP_PLAYBOOK   = "playbook"
JOURNEY_STEP_COMPLETE   = "complete"


# ── small utils ────────────────────────────────────────────────────────────────

def _as_list(v: Any) -> list[Any]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, list) else []
        except Exception:
            return []
    return v if isinstance(v, list) else []


def _as_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, dict) else {}
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


# ── helpers ────────────────────────────────────────────────────────────────

def get_outcome_options() -> list[str]:
    return [o["text"] for o in _JOURNEY["outcomes"]]


def get_domain_options(selected_outcome_text: str) -> list[str] | None:
    outcome_id = _OUTCOME_TEXT_TO_ID.get(selected_outcome_text)
    if not outcome_id:
        return None
    return list(_JOURNEY["outcome_domains"].get(outcome_id, []))


def get_task_options(selected_domain: str) -> list[str] | None:
    tasks = _JOURNEY["domain_tasks"].get(selected_domain)
    return list(tasks) if tasks else None


def get_scale_questions() -> list[dict[str, Any]]:
    """Return all scale questions with their IDs, question text, and options."""
    return _SCALE_QUESTIONS


def get_scale_question_by_id(q_id: str) -> dict[str, Any] | None:
    """Return a specific scale question by its ID."""
    for q in _SCALE_QUESTIONS:
        if q.get("id") == q_id:
            return q
    return None


def _build_scale_message(index: int, acc: dict[str, Any]) -> dict[str, Any]:
    """Build assistant message for one scale question, carrying accumulated context."""
    q = _SCALE_QUESTIONS[index]
    options = list(q["options"])
    scale_answers: dict = dict(acc.get("scaleAnswers") or {})

    if q.get("multi_select"):
        already = scale_answers.get(q["id"], [])
        if isinstance(already, list) and already:
            selected_labels = ", ".join(already)
            content = (
                f"**{q['question']}**\n\n"
                f"Selected so far: {selected_labels}\n\n"
                "Pick more or click **Done ✓** to continue."
            )
            remaining = [o for o in options if o not in already]
            options = remaining + ["Done ✓"]
        else:
            content = f"**{q['question']}**"
    else:
        content = f"**{q['question']}**"

    return {
        "content": content,
        "options": options,
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_SCALE,
        "journeySelections": {**acc, "scaleIndex": index, "scaleAnswers": scale_answers},
        "kind": "final",
    }


def start_scale_questions(url: str = "", acc: dict[str, Any] | None = None) -> dict[str, Any]:
    """First scale question message, called after URL typed or Skip."""
    base = dict(acc or {})
    if url:
        base["websiteUrl"] = url
    intro = (
        f"Thanks! I've noted your URL: **{url}**\n\n" if url
        else "No problem, I'll provide general recommendations.\n\n"
    )
    first = _SCALE_QUESTIONS[0]
    return {
        "content": (
            f"{intro}To give you the most relevant recommendations, "
            "I have a few quick questions about your business.\n\n"
            f"**{first['question']}**"
        ),
        "options": list(first["options"]),
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_SCALE,
        "journeySelections": {**base, "scaleIndex": 0, "scaleAnswers": {}},
        "kind": "final",
    }


def _diagnostic_message(question: dict[str, Any], acc: dict[str, Any]) -> dict[str, Any]:
    """Wrap an RCA DynamicQuestion dict as a journey message."""
    options = list(question.get("options") or [])
    allows_free = question.get("allows_free_text", True)
    return {
        "content": question.get("question", ""),
        "options": options,
        "allowCustomAnswer": allows_free,
        "journeyStep": JOURNEY_STEP_DIAGNOSTIC,
        "journeySelections": acc,
        "kind": "final",
    }


async def _ensure_onboarding_session(acc: dict[str, Any]) -> str:
    """
    Create (or reuse) an onboarding session for the journey.
    Returns the session_id stored in acc, or creates a new one.
    """
    existing_sid = str(acc.get("onboardingSessionId") or "").strip()
    if existing_sid:
        return existing_sid

    from app.services.onboarding_service import upsert_onboarding_patch

    sid = str(uuid4())
    outcome_text = str(acc.get("outcome") or "")
    outcome_id = _OUTCOME_TEXT_TO_ID.get(outcome_text, "")
    patch: dict[str, Any] = {}
    if outcome_id:
        patch["outcome"] = outcome_id
    if acc.get("domain"):
        patch["domain"] = str(acc["domain"])
    if acc.get("task"):
        patch["task"] = str(acc["task"])
    if acc.get("websiteUrl"):
        patch["website_url"] = str(acc["websiteUrl"])
    if acc.get("scaleAnswers"):
        patch["scale_answers"] = acc["scaleAnswers"]

    await upsert_onboarding_patch(sid, patch)
    return sid


# ── playbook stream ────────────────────────────────────────────────────────────

async def _playbook_start(acc: dict[str, Any]) -> dict[str, Any]:
    """Start the playbook task stream and return a waiting message."""
    from app.task_stream.service import TaskStreamService
    from app.task_stream.registry import TASK_STREAM_REGISTRY

    onboarding_id = str(acc.get("onboardingSessionId") or "").strip()
    if not onboarding_id:
        return _complete_message(acc)

    task_type = "playbook/onboarding-generate"
    task_fn = TASK_STREAM_REGISTRY.get(task_type)
    if not task_fn:
        return _complete_message(acc)

    try:
        service = TaskStreamService()
        started = await service.start_task_stream(
            task_type=task_type,
            task_fn=task_fn,
            payload={"onboarding_id": onboarding_id},
            onboarding_id=onboarding_id,
            user_id=None,
            resume_if_exists=True,
        )
        stream_id = str(started.get("stream_id") or "")
    except Exception:
        return _complete_message(acc)

    return {
        "content": (
            "Generating your personalised playbook — this may take a moment. "
            "I'll show it here as soon as it's ready."
        ),
        "options": [],
        "allowCustomAnswer": False,
        "journeyStep": JOURNEY_STEP_PLAYBOOK,
        "journeySelections": {**acc, "streamId": stream_id},
        "kind": "final",
    }


# ── main step machine ──────────────────────────────────────────────────────────

async def next_step(
    current_step: str,
    selected_option: str,
    journey_selections: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Advance the journey by one step.
    `journey_selections` is the full accumulated context from the last assistant message.
    Returns the next assistant message payload, or None if step is unrecognised.
    """
    prev = dict(journey_selections or {})

    # ── Playbook retry ──────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_PLAYBOOK:
        # Any message on the playbook step restarts generation (handles retry after failure)
        return await _playbook_start(prev)

    # ── Q1: Outcome ─────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_OUTCOME:
        domains = get_domain_options(selected_option)
        if not domains:
            return None
        outcome_id = _OUTCOME_TEXT_TO_ID.get(selected_option, "")
        acc = {**prev, "outcome": selected_option, "outcomeId": outcome_id}
        return {
            "content": f"Great choice! Which area within **{selected_option}** do you want to focus on?",
            "options": domains,
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_DOMAIN,
            "journeySelections": acc,
        }

    # ── Q2: Domain ──────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_DOMAIN:
        tasks = get_task_options(selected_option)
        if not tasks:
            return None
        acc = {**prev, "domain": selected_option}
        return {
            "content": f"What specific task do you need help with in **{selected_option}**?",
            "options": tasks,
            "allowCustomAnswer": False,
            "journeyStep": JOURNEY_STEP_TASK,
            "journeySelections": acc,
        }

    # ── Q3: Task ────────────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_TASK:
        acc = {**prev, "task": selected_option}
        return {
            "content": (
                f"Perfect! To give you the most personalised recommendations for **{selected_option}**, "
                "please share your **Website URL** or **Google Business Profile URL**.\n\n"
                "You can also click **Skip** and I'll provide general guidance instead."
            ),
            "options": ["Skip"],
            "allowCustomAnswer": True,
            "journeyStep": JOURNEY_STEP_URL,
            "journeySelections": acc,
        }

    # ── URL: Skip clicked ────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_URL:
        return start_scale_questions(url="", acc=prev)

    # ── Scale questions ──────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_SCALE:
        scale_index: int = int(prev.get("scaleIndex", 0))
        scale_answers: dict = dict(prev.get("scaleAnswers") or {})
        q = _SCALE_QUESTIONS[scale_index]
        q_id = q["id"]

        if q.get("multi_select"):
            if selected_option == "Done ✓":
                pass  # fall through to advance
            else:
                current_list = scale_answers.get(q_id, [])
                if not isinstance(current_list, list):
                    current_list = []
                if selected_option not in current_list:
                    current_list = current_list + [selected_option]
                scale_answers[q_id] = current_list
                acc = {**prev, "scaleAnswers": scale_answers, "scaleIndex": scale_index}
                return _build_scale_message(scale_index, acc)
        else:
            scale_answers[q_id] = selected_option

        next_index = scale_index + 1
        acc = {**prev, "scaleAnswers": scale_answers}

        if next_index < len(_SCALE_QUESTIONS):
            return _build_scale_message(next_index, acc)

        # All scale questions answered → create onboarding session + first RCA question
        from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

        sid = await _ensure_onboarding_session({**acc})
        acc["onboardingSessionId"] = sid

        rca = await generate_next_rca_question_for_onboarding(onboarding_id=sid, answer=None)
        if rca.get("status") == "question" and rca.get("question"):
            q_dict = rca["question"]
            if hasattr(q_dict, "__dict__"):
                q_dict = q_dict.__dict__
            return _diagnostic_message(q_dict, acc)

        # RCA returned complete immediately — move to gap/playbook
        return await _playbook_start(acc)

    # ── Diagnostic (RCA) ─────────────────────────────────────────────────────
    if current_step == JOURNEY_STEP_DIAGNOSTIC:
        from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

        sid = str(prev.get("onboardingSessionId") or "").strip()
        if not sid:
            sid = await _ensure_onboarding_session(prev)
            prev = {**prev, "onboardingSessionId": sid}

        rca = await generate_next_rca_question_for_onboarding(onboarding_id=sid, answer=selected_option)

        if rca.get("status") == "question" and rca.get("question"):
            q_dict = rca["question"]
            if hasattr(q_dict, "__dict__"):
                q_dict = q_dict.__dict__
            return _diagnostic_message(q_dict, {**prev})

        # Diagnostic complete → start playbook
        return await _playbook_start({**prev})

    return None


def _complete_message(acc: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": (
            "Great, I have everything I need! Let me now put together personalised "
            "recommendations for you. Feel free to ask me anything or describe what "
            "you'd like to explore further."
        ),
        "options": [],
        "allowCustomAnswer": True,
        "journeyStep": JOURNEY_STEP_COMPLETE,
        "journeySelections": acc,
        "kind": "final",
    }