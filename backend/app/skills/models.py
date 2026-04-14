from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from pathlib import Path

ProgressCb = Callable[[dict[str, Any]], Awaitable[None]]
PageCb = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class SkillManifest:
    id: str
    name: str
    description: str
    emoji: str
    entry: str
    directory: Path
    stages: list[str]
    stage_labels: dict[str, str]
    input_schema: dict[str, Any] | None
    summary_mode: str = "single"
    summary_array_path: str | None = None
    summary_content_field: str = "snapshot"
    summary_url_field: str = "url"


@dataclass
class SkillRunResult:
    status: str
    text: str
    error: str | None
    data: Any
    duration_ms: int

