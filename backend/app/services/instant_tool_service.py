"""
═══════════════════════════════════════════════════════════════
INSTANT TOOL SERVICE — Zero-latency Q1×Q2×Q3 tool lookup
═══════════════════════════════════════════════════════════════
Returns pre-mapped tool recommendations for the user's
Q1 (outcome) → Q2 (domain) → Q3 (task) selection
in <1ms — pure dict lookup, no LLM, no RAG, no network calls.

Data source: tools_by_q1_q2_q3.json
(built from tools.xlsx + categories CSV via resource/generate_mapping.py)
"""

import json
from functools import lru_cache
from pathlib import Path

import structlog

logger = structlog.get_logger()

_DATA_PATH = Path(__file__).parent.parent / "data" / "tools_by_q1_q2_q3.json"

# ── Outcome label → outcome ID normalization ───────────────────
_OUTCOME_LABEL_TO_ID = {
    "lead generation": "lead-generation",
    "lead generation (marketing, seo & social)": "lead-generation",
    "lead generation (marketing, seo & social )": "lead-generation",
    "sales & retention": "sales-retention",
    "sales & retention (calling, support & expansion)": "sales-retention",
    "sales & retention (calling , support & expansion)": "sales-retention",
    "business strategy": "business-strategy",
    "business strategy (intelligence, market & org)": "business-strategy",
    "business strategy (intelligence , market & org)": "business-strategy",
    "save time": "save-time",
    "save time (automation workflow, extract pdf, bulk task)": "save-time",
    "save time (automation workflow , extract pdf, bulk task)": "save-time",
}

@lru_cache(maxsize=1)
def _load_data() -> dict:
    """Load the pre-mapped JSON once and cache in memory."""
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        total_paths = sum(
            len(tasks)
            for domains in data.values()
            for tasks in domains.values()
        )
        logger.info(
            "tools_by_q1_q2_q3.json loaded",
            outcomes=len(data),
            total_paths=total_paths,
        )
        return data
    except Exception as e:
        logger.error("Failed to load tools_by_q1_q2_q3.json", error=str(e))
        return {}


def _resolve_outcome_id(outcome: str) -> str:
    """Normalize various outcome labels/IDs to a canonical outcome ID."""
    if not outcome:
        return ""
    low = outcome.lower().strip()
    # Already a valid ID
    if low in ("lead-generation", "sales-retention", "business-strategy", "save-time"):
        return low
    # Label lookup
    if low in _OUTCOME_LABEL_TO_ID:
        return _OUTCOME_LABEL_TO_ID[low]
    # Fuzzy keyword fallback
    if "lead gen" in low:
        return "lead-generation"
    if "sales" in low or "retention" in low:
        return "sales-retention"
    if "strategy" in low or "intelligence" in low:
        return "business-strategy"
    if "save time" in low or "automation" in low:
        return "save-time"
    return low


def get_tools_for_q1_q2_q3(
    outcome: str,
    domain: str,
    task: str,
    limit: int = 10,
) -> dict:
    """
    Instant deterministic tool lookup by Q1×Q2×Q3.

    Returns dict with:
      - 'tools': list of tool dicts (up to `limit`)
      - 'message': user-facing message
      - 'match_type': 'exact' | 'domain_fallback' | 'outcome_fallback' | 'empty'
      - 'count': number of tools returned

    Performance: <1ms — pure dictionary key lookup.
    """
    data = _load_data()
    if not data:
        return _empty_result("Tool data unavailable.")

    outcome_id = _resolve_outcome_id(outcome)

    # ── Level 1: Exact Q1→Q2→Q3 match ─────────────────────────
    outcome_data = data.get(outcome_id, {})
    domain_data = outcome_data.get(domain, {})
    tools = domain_data.get(task, [])

    if tools:
        return _build_result(
            tools[:limit],
            match_type="exact",
            outcome_id=outcome_id,
            domain=domain,
            task=task,
        )

    # ── Level 2: Fuzzy task match within same domain ───────────
    # Try case-insensitive or substring match on task name
    task_lower = task.lower().strip()
    for stored_task, stored_tools in domain_data.items():
        if stored_task.lower().strip() == task_lower:
            return _build_result(
                stored_tools[:limit],
                match_type="exact",
                outcome_id=outcome_id,
                domain=domain,
                task=stored_task,
            )

    # ── Level 3: Domain-level fallback (aggregate top tools) ───
    if domain_data:
        aggregated = _aggregate_top_tools(domain_data, limit)
        if aggregated:
            return _build_result(
                aggregated,
                match_type="domain_fallback",
                outcome_id=outcome_id,
                domain=domain,
                task=task,
            )

    # ── Level 4: Fuzzy domain match within same outcome ────────
    domain_lower = domain.lower().strip()
    for stored_domain, stored_tasks in outcome_data.items():
        if stored_domain.lower().strip() == domain_lower:
            aggregated = _aggregate_top_tools(stored_tasks, limit)
            if aggregated:
                return _build_result(
                    aggregated,
                    match_type="domain_fallback",
                    outcome_id=outcome_id,
                    domain=stored_domain,
                    task=task,
                )

    # ── Level 5: Outcome-level fallback ────────────────────────
    if outcome_data:
        all_tasks = {}
        for d_tasks in outcome_data.values():
            all_tasks.update(d_tasks)
        aggregated = _aggregate_top_tools(all_tasks, limit)
        if aggregated:
            return _build_result(
                aggregated,
                match_type="outcome_fallback",
                outcome_id=outcome_id,
                domain=domain,
                task=task,
            )

    return _empty_result("No tools found for this combination.")


def _aggregate_top_tools(tasks_dict: dict, limit: int) -> list:
    """Aggregate tools across multiple tasks, deduplicate, sort by score."""
    seen = set()
    all_tools = []
    for task_tools in tasks_dict.values():
        for t in task_tools:
            name_key = t["name"].lower().strip()
            if name_key not in seen:
                seen.add(name_key)
                all_tools.append(t)
    all_tools.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
    return all_tools[:limit]


def _build_result(
    tools: list,
    match_type: str,
    outcome_id: str,
    domain: str,
    task: str,
) -> dict:
    message = (
        f"Here are the top-rated tools for your selection — "
        f"curated from verified reviews and ratings."
    )
    logger.info(
        "Instant Q1Q2Q3 tool lookup",
        match_type=match_type,
        outcome=outcome_id,
        domain=domain,
        task=task[:60],
        count=len(tools),
    )
    return {
        "tools": tools,
        "message": message,
        "match_type": match_type,
        "count": len(tools),
    }


def _empty_result(message: str) -> dict:
    return {
        "tools": [],
        "message": message,
        "match_type": "empty",
        "count": 0,
    }
