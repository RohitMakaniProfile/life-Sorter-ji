from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import HTTPException

from app.db import get_pool
from app.models.session import DynamicQuestion
from app.services.claude_rca_service import generate_next_rca_question
from app.services.persona_doc_service import get_diagnostic_sections
from app.services.rca_tree_service import get_first_question, get_next_from_tree
# No dependency on legacy session state.


def _dynamic_question_from_tree(q: dict[str, Any]) -> DynamicQuestion:
    return DynamicQuestion(
        question=q.get("question", ""),
        options=q.get("options", []) or [],
        allows_free_text=True,
        section=q.get("section", "") or "",
        section_label=q.get("section_label", "") or "",
        insight=q.get("insight", "") or "",
    )


def _dynamic_question_from_section(section: dict[str, Any]) -> DynamicQuestion:
    # persona_doc_service sections are shaped differently from the decision-tree.
    return DynamicQuestion(
        question=section.get("question", ""),
        options=section.get("items", []) or [],
        allows_free_text=section.get("allows_free_text", True),
        section=section.get("key", "") or "",
        section_label=section.get("label", "") or "",
        insight=section.get("insight", "") or "",
    )


def _normalize_rca_qa(rca_qa: Any) -> list[dict[str, Any]]:
    if isinstance(rca_qa, str):
        try:
            rca_qa = json.loads(rca_qa)
        except Exception:
            return []
    if isinstance(rca_qa, list):
        return rca_qa
    return []


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return value if isinstance(value, dict) else {}


def _normalize_questions_answers(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return value if isinstance(value, list) else []


def _get_pending_idx(rca_qa: list[dict[str, Any]]) -> Optional[int]:
    if rca_qa and isinstance(rca_qa[-1], dict) and rca_qa[-1].get("answer") is None:
        return len(rca_qa) - 1
    return None


def _apply_answer_to_last_pending(rca_qa: list[dict[str, Any]], answer: str) -> None:
    if not rca_qa:
        raise HTTPException(status_code=400, detail="No pending question found to answer")
    last = rca_qa[-1]
    if not isinstance(last, dict):
        raise HTTPException(status_code=400, detail="Pending question transcript is corrupted")
    if last.get("answer") is not None:
        raise HTTPException(status_code=400, detail="Last question already has an answer")
    last["answer"] = answer
    rca_qa[-1] = last


def _build_rca_history(rca_qa: list[dict[str, Any]]) -> list[dict[str, str]]:
    # Matching/generation history: only questions that already have an answer.
    return [
        {"question": str(item.get("question") or ""), "answer": str(item.get("answer") or "")}
        for item in rca_qa
        if isinstance(item, dict) and item.get("answer") is not None
    ]


def _outcome_label(outcome: str) -> str:
    # Keep this mapping local so onboarding RCA stays self-contained.
    labels = {
        "lead-generation": "Lead Generation",
        "sales-retention": "Sales & Retention",
        "business-strategy": "Business Strategy",
        "save-time": "Save Time",
    }
    return labels.get(outcome or "", "") or ""


def _try_static_tree_question(
    *,
    outcome: str,
    domain: str,
    task: str,
    rca_history: list[dict[str, str]],
) -> Optional[DynamicQuestion]:
    if len(rca_history) == 0:
        tree_q1 = get_first_question(outcome=outcome, domain=domain, task=task)
        if tree_q1 and tree_q1.get("question"):
            return _dynamic_question_from_tree(tree_q1)
        return None

    tree_next = get_next_from_tree(outcome=outcome, domain=domain, task=task, rca_history=rca_history)
    if tree_next and tree_next.get("question"):
        return _dynamic_question_from_tree(tree_next)
    return None


async def _try_llm_question(
    *,
    outcome: str,
    outcome_label: str,
    domain: str,
    task: str,
    diagnostic: dict[str, Any],
    rca_history: list[dict[str, str]],
    business_profile: dict[str, Any] | None,
    gbp_data: dict[str, Any] | None,
) -> tuple[Optional[DynamicQuestion], str, str]:
    complete_summary = ""
    complete_handoff = ""
    claude_result = await generate_next_rca_question(
        outcome=outcome,
        outcome_label=outcome_label,
        domain=domain,
        task=task,
        diagnostic_context=diagnostic or {},
        rca_history=rca_history,
        business_profile=business_profile,
        gbp_data=gbp_data,
    )

    if claude_result and claude_result.get("status") == "question":
        dyn_question = DynamicQuestion(
            question=claude_result.get("question", ""),
            options=claude_result.get("options", []) or [],
            allows_free_text=True,
            section=claude_result.get("section", "rca") or "rca",
            section_label=claude_result.get("section_label", "Diagnostic") or "Diagnostic",
            insight=claude_result.get("insight", "") or "",
        )
        return dyn_question, complete_summary, complete_handoff

    if claude_result and claude_result.get("status") == "complete":
        complete_summary = claude_result.get("summary", "") or ""
        raw_handoff = claude_result.get("handoff", "") or ""
        if isinstance(raw_handoff, list):
            complete_handoff = "\n".join(f"• {item}" for item in raw_handoff)
        else:
            complete_handoff = str(raw_handoff or "")

    return None, complete_summary, complete_handoff


async def _persist_rca_complete_fields(
    conn,
    *,
    onboarding_id: Any,
    rca_summary: str,
    rca_handoff: str,
) -> None:
    await conn.execute(
        """
        UPDATE onboarding
        SET rca_summary = $1,
            rca_handoff = $2,
            updated_at = NOW()
        WHERE id = $3
        """,
        rca_summary or "",
        rca_handoff or "",
        onboarding_id,
    )


def _try_static_section_fallback(
    *,
    diagnostic: dict[str, Any],
    answered_count: int,
) -> Optional[DynamicQuestion]:
    sections = diagnostic.get("sections") or []
    if answered_count < 0 or answered_count >= len(sections):
        return None
    section = sections[answered_count]
    if not isinstance(section, dict):
        return None
    return _dynamic_question_from_section(section)


async def _persist_rca_qa(conn, *, onboarding_id: Any, rca_qa: list[dict[str, Any]]) -> None:
    await conn.execute(
        """
        UPDATE onboarding
        SET rca_qa = $1::jsonb
        WHERE id = $2
        """,
        json.dumps(rca_qa),
        onboarding_id,
    )


async def generate_next_rca_question_for_onboarding(
    *,
    session_id: str,
    answer: Optional[str],
) -> dict[str, Any]:
    """
    Minimal onboarding logic:
      - read `onboarding.outcome/domain/task` and `onboarding.rca_qa`
      - if `answer` provided, fill the last pending question
      - generate the next question via:
          1) static `rca_decision_tree.json` hit
          2) LLM fallback (`generate_next_rca_question`)
          3) static sections fallback (if LLM fails)
      - persist updated `onboarding.rca_qa` (JSONB transcript)
    """
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, outcome, domain, task, rca_qa, scale_answers, questions_answers
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

        onboarding_id = row.get("id")
        outcome = row.get("outcome") or ""
        domain = row.get("domain") or ""
        task = row.get("task") or ""
        scale_answers = _normalize_json_dict(row.get("scale_answers"))

        rca_qa = _normalize_rca_qa(row.get("rca_qa"))
        questions_answers = _normalize_questions_answers(row.get("questions_answers"))
        pending_idx = _get_pending_idx(rca_qa)

        if answer is not None:
            _apply_answer_to_last_pending(rca_qa, answer)
            # Also append into unified Q&A log (optional column).
            try:
                last = rca_qa[-1] if rca_qa else {}
                if isinstance(last, dict):
                    questions_answers.append(
                        {
                            "question": str(last.get("question") or ""),
                            "answer": str(last.get("answer") or ""),
                            "question_type": "rca",
                        }
                    )
            except Exception:
                # Best-effort only; RCA transcript remains source of truth.
                pass

        rca_history = _build_rca_history(rca_qa)

        # Diagnostic context (used by LLM + static section fallback).
        diagnostic = get_diagnostic_sections(domain=domain, task=task) or {}
        outcome_label = _outcome_label(outcome)

        dyn_question = _try_static_tree_question(
            outcome=outcome,
            domain=domain,
            task=task,
            rca_history=rca_history,
        )

        match_source = "tree" if dyn_question is not None else "llm"
        complete_summary = ""
        complete_handoff = ""

        if dyn_question is None:
            dyn_question, complete_summary, complete_handoff = await _try_llm_question(
                outcome=outcome,
                outcome_label=outcome_label,
                domain=domain,
                task=task,
                diagnostic=diagnostic,
                rca_history=rca_history,
                business_profile=scale_answers or None,
                gbp_data=None,
            )

            if dyn_question is None:
                # If LLM completed the diagnostic, persist summary/handoff and return complete.
                if complete_summary or complete_handoff:
                    await _persist_rca_complete_fields(
                        conn,
                        onboarding_id=onboarding_id,
                        rca_summary=complete_summary,
                        rca_handoff=complete_handoff,
                    )
                    return {
                        "status": "complete",
                        "question": None,
                        "match_source": "llm",
                        "complete_summary": complete_summary or "Diagnostic complete.",
                        "complete_handoff": complete_handoff or "",
                    }
                dyn_question = _try_static_section_fallback(diagnostic=diagnostic, answered_count=len(rca_history))
                if dyn_question is None:
                    return {
                        "status": "complete",
                        "question": None,
                        "match_source": "static_fallback",
                        "complete_summary": complete_summary or "Diagnostic complete.",
                    }
                match_source = "static_fallback"

        if dyn_question is None:
            return {
                "status": "complete",
                "question": None,
                "match_source": match_source,
                "complete_summary": complete_summary or "Diagnostic complete.",
                "complete_handoff": complete_handoff or "",
            }

        if pending_idx is not None and answer is None:
            rca_qa[pending_idx] = {"question": dyn_question.question, "answer": None}
        else:
            rca_qa.append({"question": dyn_question.question, "answer": None})

        await _persist_rca_qa(conn, onboarding_id=onboarding_id, rca_qa=rca_qa)
        if questions_answers is not None:
            await conn.execute(
                """
                UPDATE onboarding
                SET questions_answers = $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2
                """,
                json.dumps(questions_answers),
                onboarding_id,
            )

        return {"status": "question", "question": dyn_question, "match_source": match_source, "complete_summary": ""}

