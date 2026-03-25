"""
═══════════════════════════════════════════════════════════════
RCA TREE SERVICE — Instant Lookup from Pre-Generated Decision Tree
═══════════════════════════════════════════════════════════════
Serves pre-generated RCA questions from a JSON decision tree.
Falls back to live LLM call if no match found (custom input / "Something else").

Tree structure:
  "outcome|domain|task" → {
      q1: {question, options, insight, ...},
      task_filter: {filtered_items, ...},
      branches: {
          "Option A text": {question, options, ...},          ← Q2 for Option A
          "Option B text": {question, options, ...},          ← Q2 for Option B
          ...each Q2 has sub_branches for Q3/Complete
      }
  }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

_TREE: dict[str, Any] = {}
_LOADED = False

TREE_PATH = Path(__file__).resolve().parent.parent / "data" / "rca_decision_tree.json"


def load_tree():
    """Load the pre-generated decision tree into memory."""
    global _TREE, _LOADED

    if _LOADED:
        return

    if not TREE_PATH.exists():
        logger.warning("RCA decision tree not found — all calls will go to live LLM", path=str(TREE_PATH))
        _LOADED = True
        return

    with open(TREE_PATH, "r") as f:
        _TREE = json.load(f)

    _LOADED = True
    logger.info("RCA decision tree loaded", entries=len(_TREE))


def _make_key(outcome: str, domain: str, task: str) -> str:
    return f"{outcome}|{domain}|{task}"


def _fuzzy_match_option(user_answer: str, available_options: list[str]) -> str | None:
    """Match user's answer to a pre-generated option (case-insensitive, strip whitespace)."""
    answer_lower = user_answer.strip().lower()
    for opt in available_options:
        if opt.strip().lower() == answer_lower:
            return opt
    # Partial match — if user's answer is a substring or vice versa
    for opt in available_options:
        if answer_lower in opt.strip().lower() or opt.strip().lower() in answer_lower:
            return opt
    return None


def get_first_question(outcome: str, domain: str, task: str) -> dict | None:
    """
    Look up pre-generated first RCA question for this task.

    Returns dict with {question, options, insight, ...} or None if not found.
    """
    load_tree()

    key = _make_key(outcome, domain, task)
    entry = _TREE.get(key)

    if entry and entry.get("q1"):
        logger.info("RCA tree hit: Q1", task=task[:50], key=key)
        return entry["q1"]

    logger.warning("RCA tree MISS: Q1", key=key, tree_keys_sample=list(_TREE.keys())[:3])
    return None


def get_task_filter(outcome: str, domain: str, task: str) -> dict | None:
    """
    Look up pre-generated task alignment filter.

    Returns dict with {filtered_items, deferred_items, task_execution_summary} or None.
    """
    load_tree()

    key = _make_key(outcome, domain, task)
    entry = _TREE.get(key)

    if entry and entry.get("task_filter"):
        logger.info("RCA tree hit: task_filter", task=task[:50])
        return entry["task_filter"]

    return None


def get_next_from_tree(
    outcome: str,
    domain: str,
    task: str,
    rca_history: list[dict[str, str]],
) -> dict | None:
    """
    Look up the next question from the decision tree based on Q&A history.

    Matches the user's answers against pre-generated option branches.
    Returns None if user typed custom text ("Something else") or no match found.
    """
    load_tree()

    key = _make_key(outcome, domain, task)
    entry = _TREE.get(key)

    if not entry:
        return None

    num_answers = len(rca_history)

    if num_answers == 0:
        # Return Q1
        return entry.get("q1")

    if num_answers == 1:
        # User answered Q1 — look up Q2 in branches
        user_answer = rca_history[0].get("answer", "")
        branches = entry.get("branches", {})

        if not branches:
            return None

        matched_opt = _fuzzy_match_option(user_answer, list(branches.keys()))
        if matched_opt:
            result = branches[matched_opt]
            logger.info("RCA tree hit: Q2", task=task[:40], option=matched_opt[:40])
            return result
        return None

    if num_answers == 2:
        # User answered Q1 + Q2 — look up Q3 in sub_branches
        q1_answer = rca_history[0].get("answer", "")
        q2_answer = rca_history[1].get("answer", "")

        branches = entry.get("branches", {})
        matched_q1 = _fuzzy_match_option(q1_answer, list(branches.keys()))
        if not matched_q1:
            return None

        q2_data = branches[matched_q1]
        sub_branches = q2_data.get("sub_branches", {})
        if not sub_branches:
            return None

        matched_q2 = _fuzzy_match_option(q2_answer, list(sub_branches.keys()))
        if matched_q2:
            result = sub_branches[matched_q2]
            logger.info("RCA tree hit: Q3/Complete", task=task[:40])
            return result

    # num_answers >= 3 or no match — need live LLM
    return None


def get_tree_stats() -> dict:
    """Return stats about the loaded tree."""
    load_tree()

    total_tasks = len(_TREE)
    tasks_with_branches = sum(1 for v in _TREE.values() if v.get("branches"))
    total_branches = sum(len(v.get("branches", {})) for v in _TREE.values())
    total_sub = sum(
        len(b.get("sub_branches", {}))
        for v in _TREE.values()
        for b in v.get("branches", {}).values()
        if isinstance(b, dict)
    )

    return {
        "total_tasks": total_tasks,
        "tasks_with_q1": total_tasks,
        "tasks_with_q2_branches": tasks_with_branches,
        "total_q2_branches": total_branches,
        "total_q3_sub_branches": total_sub,
        "tree_file": str(TREE_PATH),
        "tree_exists": TREE_PATH.exists(),
    }
