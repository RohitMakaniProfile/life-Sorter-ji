"""
═══════════════════════════════════════════════════════════════
CATEGORIES DATA — Load categories from CSV
═══════════════════════════════════════════════════════════════
Parses the categories CSV into structured data for lookups.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger()

CATEGORIES_CSV = Path(__file__).parent / "categories.csv"


class CategoryEntry:
    """A single row from the categories CSV."""

    def __init__(self, growth_bucket: str, sub_category: str, task: str):
        self.growth_bucket = growth_bucket.strip()
        self.sub_category = sub_category.strip()
        self.task = task.strip()


@lru_cache(maxsize=1)
def load_categories() -> list[CategoryEntry]:
    """Load all category entries from the CSV file."""
    entries = []
    try:
        with open(CATEGORIES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                entries.append(
                    CategoryEntry(
                        growth_bucket=row.get("Growth Bucket", ""),
                        sub_category=row.get("Sub-Category", ""),
                        task=row.get("Task / Solution", ""),
                    )
                )
        logger.info("Categories loaded", count=len(entries))
    except Exception as e:
        logger.error("Failed to load categories CSV", error=str(e))
    return entries


def get_tasks_for_domain(domain: str) -> list[str]:
    """Get all tasks for a given sub-category/domain."""
    entries = load_categories()
    domain_lower = domain.lower().strip()
    return [
        e.task
        for e in entries
        if e.sub_category.lower().strip() == domain_lower
    ]


def get_domains_for_outcome(outcome_label: str) -> list[str]:
    """Get all unique sub-categories for a given growth bucket."""
    entries = load_categories()
    outcome_lower = outcome_label.lower().strip()
    seen = set()
    domains = []
    for e in entries:
        if outcome_lower in e.growth_bucket.lower():
            if e.sub_category not in seen:
                seen.add(e.sub_category)
                domains.append(e.sub_category)
    return domains


def get_growth_buckets() -> list[str]:
    """Get all unique growth bucket names."""
    entries = load_categories()
    seen = set()
    buckets = []
    for e in entries:
        if e.growth_bucket not in seen:
            seen.add(e.growth_bucket)
            buckets.append(e.growth_bucket)
    return buckets


def find_category_entry(
    domain: str, task: str
) -> Optional[CategoryEntry]:
    """Find a specific category entry by domain and task."""
    entries = load_categories()
    domain_lower = domain.lower().strip()
    task_lower = task.lower().strip()
    for e in entries:
        if (
            e.sub_category.lower().strip() == domain_lower
            and e.task.lower().strip() == task_lower
        ):
            return e
    return None
