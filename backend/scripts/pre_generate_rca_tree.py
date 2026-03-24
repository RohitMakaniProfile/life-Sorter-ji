"""
═══════════════════════════════════════════════════════════════
PRE-GENERATE RCA DECISION TREE
═══════════════════════════════════════════════════════════════
One-time script to pre-generate all RCA questions for every
outcome → domain → task combination.

Phase 1: Generate Q1 + Task Filter for all 139 tasks (saves ~45s/session)
Phase 2: Generate Q2 for each Q1 option (saves ~15s more)
Phase 3: Full tree Q3 + Complete (saves ~30s more → RCA = 0ms)

Usage:
    cd backend
    source .venv/bin/activate
    python -m scripts.pre_generate_rca_tree --phase 1
    python -m scripts.pre_generate_rca_tree --phase 2
    python -m scripts.pre_generate_rca_tree --phase 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# Add backend to path so app imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.persona_doc_service import preload_all_docs, get_diagnostic_sections
from app.services.claude_rca_service import generate_next_rca_question, generate_task_alignment_filter
from app.config import get_settings

# Output file
TREE_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "rca_decision_tree.json"

# Load all combos from tools_by_q1_q2_q3.json
TOOLS_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "tools_by_q1_q2_q3.json"

OUTCOME_LABELS = {
    "lead-generation": "Lead Generation",
    "sales-retention": "Sales & Retention",
    "business-strategy": "Business Strategy",
    "save-time": "Save Time",
}


def load_all_combos() -> list[dict]:
    """Load all outcome → domain → task combos from tools JSON."""
    with open(TOOLS_PATH, "r") as f:
        data = json.load(f)

    combos = []
    for outcome, domains in data.items():
        if not isinstance(domains, dict):
            continue
        for domain, tasks in domains.items():
            if not isinstance(tasks, dict):
                continue
            for task in tasks.keys():
                combos.append({
                    "outcome": outcome,
                    "outcome_label": OUTCOME_LABELS.get(outcome, outcome),
                    "domain": domain,
                    "task": task,
                })
    return combos


def load_existing_tree() -> dict:
    """Load existing tree or return empty."""
    if TREE_PATH.exists():
        with open(TREE_PATH, "r") as f:
            return json.load(f)
    return {}


def save_tree(tree: dict):
    """Save tree to JSON."""
    with open(TREE_PATH, "w") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)
    print(f"Saved tree to {TREE_PATH} ({len(json.dumps(tree))} bytes)")


def make_key(outcome: str, domain: str, task: str) -> str:
    """Create a lookup key."""
    return f"{outcome}|{domain}|{task}"


async def generate_q1_for_task(combo: dict, diagnostic: dict) -> dict | None:
    """Generate the first RCA question for a task."""
    result = await generate_next_rca_question(
        outcome=combo["outcome"],
        outcome_label=combo["outcome_label"],
        domain=combo["domain"],
        task=combo["task"],
        diagnostic_context=diagnostic,
        rca_history=[],
    )

    if result and result.get("status") == "question":
        return {
            "question": result["question"],
            "options": result.get("options", []),
            "insight": result.get("insight", ""),
            "acknowledgment": result.get("acknowledgment", ""),
            "section": result.get("section", ""),
            "section_label": result.get("section_label", ""),
            "diagnostic_intent": result.get("diagnostic_intent", ""),
            "cumulative_insight": result.get("cumulative_insight", ""),
        }
    return None


async def generate_filter_for_task(task: str, diagnostic: dict) -> dict | None:
    """Generate the task alignment filter."""
    result = await generate_task_alignment_filter(
        task=task,
        diagnostic_context=diagnostic,
    )

    if result and result.get("filtered_items"):
        return {
            "task_execution_summary": result.get("task_execution_summary", ""),
            "filtered_items": result.get("filtered_items", {}),
            "deferred_items": result.get("deferred_items", []),
        }
    return None


async def generate_q_for_answer(
    combo: dict,
    diagnostic: dict,
    rca_history: list[dict],
    running_summary: str = "",
) -> dict | None:
    """Generate next question given history."""
    result = await generate_next_rca_question(
        outcome=combo["outcome"],
        outcome_label=combo["outcome_label"],
        domain=combo["domain"],
        task=combo["task"],
        diagnostic_context=diagnostic,
        rca_history=rca_history,
        rca_running_summary=running_summary or None,
    )

    if not result:
        return None

    if result.get("status") == "question":
        return {
            "status": "question",
            "question": result["question"],
            "options": result.get("options", []),
            "insight": result.get("insight", ""),
            "acknowledgment": result.get("acknowledgment", ""),
            "section": result.get("section", ""),
            "section_label": result.get("section_label", ""),
            "cumulative_insight": result.get("cumulative_insight", ""),
        }
    elif result.get("status") == "complete":
        raw_handoff = result.get("handoff", "")
        if isinstance(raw_handoff, list):
            handoff = "\n".join(f"• {item}" for item in raw_handoff)
        else:
            handoff = raw_handoff or ""
        return {
            "status": "complete",
            "summary": result.get("summary", ""),
            "acknowledgment": result.get("acknowledgment", ""),
            "handoff": handoff,
        }
    return None


async def run_phase1():
    """Phase 1: Generate Q1 + Task Filter for all tasks."""
    print("=" * 60)
    print("PHASE 1: Pre-generating Q1 + Task Filter for all tasks")
    print("=" * 60)

    preload_all_docs()
    combos = load_all_combos()
    tree = load_existing_tree()
    total = len(combos)

    print(f"Found {total} task combinations")

    settings = get_settings()
    if not settings.OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set!")
        return

    success = 0
    skipped = 0
    failed = 0

    for i, combo in enumerate(combos):
        key = make_key(combo["outcome"], combo["domain"], combo["task"])

        # Skip if already generated
        if key in tree and tree[key].get("q1"):
            skipped += 1
            print(f"[{i+1}/{total}] SKIP (exists): {combo['task'][:50]}")
            continue

        diagnostic = get_diagnostic_sections(combo["domain"], combo["task"])
        if not diagnostic:
            failed += 1
            print(f"[{i+1}/{total}] FAIL (no persona doc): {combo['domain']} → {combo['task'][:50]}")
            continue

        t0 = time.time()

        # Generate Q1 and Task Filter in parallel
        q1_result, filter_result = await asyncio.gather(
            generate_q1_for_task(combo, diagnostic),
            generate_filter_for_task(combo["task"], diagnostic),
        )

        elapsed = time.time() - t0

        if q1_result:
            tree[key] = {
                "outcome": combo["outcome"],
                "outcome_label": combo["outcome_label"],
                "domain": combo["domain"],
                "task": combo["task"],
                "q1": q1_result,
                "task_filter": filter_result,
                "branches": {},  # Q2 branches filled in Phase 2
            }
            success += 1
            print(f"[{i+1}/{total}] OK ({elapsed:.1f}s): {combo['task'][:50]}")
        else:
            failed += 1
            print(f"[{i+1}/{total}] FAIL ({elapsed:.1f}s): {combo['task'][:50]}")

        # Save every 10 tasks (in case of crash)
        if (i + 1) % 10 == 0:
            save_tree(tree)

        # Small delay to avoid rate limits
        await asyncio.sleep(0.5)

    save_tree(tree)
    print(f"\nPhase 1 complete: {success} ok, {skipped} skipped, {failed} failed")


async def run_phase2():
    """Phase 2: For each Q1, generate Q2 for each option."""
    print("=" * 60)
    print("PHASE 2: Pre-generating Q2 for each Q1 option")
    print("=" * 60)

    preload_all_docs()
    tree = load_existing_tree()

    if not tree:
        print("ERROR: No tree found. Run Phase 1 first.")
        return

    keys_with_q1 = [k for k, v in tree.items() if v.get("q1") and not v.get("branches")]
    # Also include those with empty branches
    keys_with_q1 += [k for k, v in tree.items() if v.get("q1") and isinstance(v.get("branches"), dict) and len(v["branches"]) == 0]
    keys_with_q1 = list(set(keys_with_q1))

    total = len(keys_with_q1)
    print(f"Found {total} tasks needing Q2 branches")

    success = 0
    failed = 0

    for i, key in enumerate(keys_with_q1):
        entry = tree[key]
        q1 = entry["q1"]
        options = q1.get("options", [])

        # Filter out "Something else" type options
        real_options = [o for o in options if o.lower() not in ("something else", "none of the above")]

        diagnostic = get_diagnostic_sections(entry["domain"], entry["task"])
        if not diagnostic:
            failed += 1
            continue

        combo = {
            "outcome": entry["outcome"],
            "outcome_label": entry["outcome_label"],
            "domain": entry["domain"],
            "task": entry["task"],
        }

        branches = {}

        for opt_idx, option in enumerate(real_options):
            t0 = time.time()

            rca_history = [{"question": q1["question"], "answer": option}]
            cumulative = q1.get("cumulative_insight", "")

            result = await generate_q_for_answer(
                combo, diagnostic, rca_history, running_summary=cumulative
            )
            elapsed = time.time() - t0

            if result:
                branches[option] = result
                print(f"  [{i+1}/{total}] Option {opt_idx+1}: OK ({elapsed:.1f}s)")
            else:
                print(f"  [{i+1}/{total}] Option {opt_idx+1}: FAIL ({elapsed:.1f}s)")

            await asyncio.sleep(0.5)

        entry["branches"] = branches
        tree[key] = entry
        success += 1

        print(f"[{i+1}/{total}] {entry['task'][:50]} → {len(branches)} branches")

        if (i + 1) % 5 == 0:
            save_tree(tree)

    save_tree(tree)
    print(f"\nPhase 2 complete: {success} tasks with branches")


async def run_phase3():
    """Phase 3: For each Q2 option, generate Q3/Complete."""
    print("=" * 60)
    print("PHASE 3: Pre-generating Q3/Complete for each Q2 option")
    print("=" * 60)

    preload_all_docs()
    tree = load_existing_tree()

    if not tree:
        print("ERROR: No tree found. Run Phase 1 and 2 first.")
        return

    total_branches = 0
    success = 0

    for key, entry in tree.items():
        branches = entry.get("branches", {})
        if not branches:
            continue

        q1 = entry["q1"]
        diagnostic = get_diagnostic_sections(entry["domain"], entry["task"])
        if not diagnostic:
            continue

        combo = {
            "outcome": entry["outcome"],
            "outcome_label": entry["outcome_label"],
            "domain": entry["domain"],
            "task": entry["task"],
        }

        for q1_answer, q2_data in branches.items():
            if q2_data.get("status") != "question":
                continue
            if q2_data.get("sub_branches"):
                continue  # Already done

            q2_options = q2_data.get("options", [])
            real_options = [o for o in q2_options if o.lower() not in ("something else", "none of the above")]

            sub_branches = {}

            for opt_idx, option in enumerate(real_options):
                total_branches += 1
                t0 = time.time()

                rca_history = [
                    {"question": q1["question"], "answer": q1_answer},
                    {"question": q2_data["question"], "answer": option},
                ]
                cumulative = q2_data.get("cumulative_insight", "")

                result = await generate_q_for_answer(
                    combo, diagnostic, rca_history, running_summary=cumulative
                )
                elapsed = time.time() - t0

                if result:
                    sub_branches[option] = result
                    success += 1

                await asyncio.sleep(0.5)

            q2_data["sub_branches"] = sub_branches

        if total_branches % 20 == 0 and total_branches > 0:
            save_tree(tree)

    save_tree(tree)
    print(f"\nPhase 3 complete: {success}/{total_branches} sub-branches generated")


async def main():
    parser = argparse.ArgumentParser(description="Pre-generate RCA decision tree")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], required=True,
                        help="Which phase to run (1=Q1+Filter, 2=Q2 branches, 3=Q3/Complete)")
    args = parser.parse_args()

    if args.phase == 1:
        await run_phase1()
    elif args.phase == 2:
        await run_phase2()
    elif args.phase == 3:
        await run_phase3()


if __name__ == "__main__":
    asyncio.run(main())
