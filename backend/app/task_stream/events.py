from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskStreamEvent:
    cursor: str
    seq: int
    type: str
    data: dict[str, Any]
