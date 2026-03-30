"""
═══════════════════════════════════════════════════════════════
SANDBOX LOGGER — Real-time event capture for developer panel
═══════════════════════════════════════════════════════════════
Captures LLM calls, context building, session state transitions,
and code file usage. Each chat session is uniquely identified.
Events are deduped by (session_id, event_type, fingerprint).
Supports export to .txt for offline analysis.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# ══════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    LLM = "llm"            # LLM-specific calls
    CONTEXT = "context"     # Context building events
    FLOW = "flow"           # Flow stage transitions
    FILE = "file"           # Code file usage


class SandboxLogEntry(BaseModel):
    """A single log entry in the sandbox logger."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat(timespec="milliseconds") + "Z")
    epoch_ms: float = Field(default_factory=lambda: time.time() * 1000)
    session_id: str = ""
    level: LogLevel = LogLevel.INFO
    category: str = ""        # e.g. "openai", "session", "rag", "agent"
    event: str = ""           # Short description
    detail: dict[str, Any] = {}
    code_file: str = ""       # Which code file produced this event
    duration_ms: Optional[float] = None
    fingerprint: str = ""     # For deduplication


class SessionLogBundle(BaseModel):
    """All logs for a specific session."""
    session_id: str
    started_at: str = ""
    entries: list[SandboxLogEntry] = []
    context_snapshot: dict[str, Any] = {}


# ══════════════════════════════════════════════════════════════
# In-Memory Log Store (singleton)
# ══════════════════════════════════════════════════════════════

MAX_SESSIONS = 200
MAX_ENTRIES_PER_SESSION = 500

# session_id → SessionLogBundle
_log_store: OrderedDict[str, SessionLogBundle] = OrderedDict()

# Global log (all sessions interleaved, for the "All" view)
_global_log: list[SandboxLogEntry] = []
MAX_GLOBAL = 2000

# Set of fingerprints for dedup: (session_id, fingerprint)
_seen_fingerprints: set[str] = set()


def _make_fingerprint(session_id: str, level: str, category: str, event: str, detail_keys: str) -> str:
    """Create a dedup fingerprint from key fields."""
    raw = f"{session_id}|{level}|{category}|{event}|{detail_keys}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _evict_if_needed():
    """Evict oldest sessions if above capacity."""
    while len(_log_store) > MAX_SESSIONS:
        oldest_key = next(iter(_log_store))
        del _log_store[oldest_key]


def log_event(
    session_id: str,
    level: LogLevel,
    category: str,
    event: str,
    detail: Optional[dict[str, Any]] = None,
    code_file: str = "",
    duration_ms: Optional[float] = None,
) -> Optional[SandboxLogEntry]:
    """
    Record a sandbox log event.
    Returns None if the event is a duplicate (same session + fingerprint).
    """
    detail = detail or {}

    # Build fingerprint for dedup
    detail_key_str = "|".join(sorted(str(v)[:50] for v in detail.values()))
    fp = _make_fingerprint(session_id, level.value, category, event, detail_key_str)

    dedup_key = f"{session_id}:{fp}"
    if dedup_key in _seen_fingerprints:
        return None
    _seen_fingerprints.add(dedup_key)

    entry = SandboxLogEntry(
        session_id=session_id,
        level=level,
        category=category,
        event=event,
        detail=detail,
        code_file=code_file,
        duration_ms=duration_ms,
        fingerprint=fp,
    )

    # Add to session bundle
    if session_id not in _log_store:
        _log_store[session_id] = SessionLogBundle(
            session_id=session_id,
            started_at=entry.timestamp,
        )
        _evict_if_needed()

    bundle = _log_store[session_id]
    if len(bundle.entries) < MAX_ENTRIES_PER_SESSION:
        bundle.entries.append(entry)

    # Add to global log
    if len(_global_log) >= MAX_GLOBAL:
        _global_log.pop(0)
    _global_log.append(entry)

    return entry


def update_context_snapshot(session_id: str, context: dict[str, Any]):
    """Update the running context snapshot for a session."""
    if session_id in _log_store:
        _log_store[session_id].context_snapshot = context


# ══════════════════════════════════════════════════════════════
# Query API
# ══════════════════════════════════════════════════════════════


def get_session_logs(session_id: str) -> Optional[SessionLogBundle]:
    """Get all logs for a specific session."""
    return _log_store.get(session_id)


def get_all_sessions() -> list[dict[str, Any]]:
    """Get a summary of all tracked sessions."""
    result = []
    for sid, bundle in _log_store.items():
        result.append({
            "session_id": sid,
            "started_at": bundle.started_at,
            "entry_count": len(bundle.entries),
            "context_keys": list(bundle.context_snapshot.keys()),
        })
    return result


def get_global_logs(since_ms: float = 0, limit: int = 200) -> list[SandboxLogEntry]:
    """Get recent global logs, optionally filtering by timestamp."""
    if since_ms > 0:
        filtered = [e for e in _global_log if e.epoch_ms > since_ms]
    else:
        filtered = list(_global_log)
    return filtered[-limit:]


def get_session_context(session_id: str) -> dict[str, Any]:
    """Get the context snapshot for a session."""
    bundle = _log_store.get(session_id)
    if bundle:
        return bundle.context_snapshot
    return {}


def clear_logs():
    """Clear all logs (for reset)."""
    _log_store.clear()
    _global_log.clear()
    _seen_fingerprints.clear()


# ══════════════════════════════════════════════════════════════
# Export to .txt
# ══════════════════════════════════════════════════════════════


def export_session_txt(session_id: str) -> str:
    """Export a session's logs as formatted human-readable text."""
    bundle = _log_store.get(session_id)
    if not bundle:
        return f"No logs found for session {session_id}"

    lines = [
        "=" * 72,
        f"  IKSHAN SANDBOX LOG — Session: {session_id}",
        f"  Started: {bundle.started_at}",
        f"  Entries: {len(bundle.entries)}",
        "=" * 72,
        "",
    ]

    # Context snapshot
    if bundle.context_snapshot:
        lines.append("── CONTEXT SNAPSHOT ──────────────────────────────")
        for key, val in bundle.context_snapshot.items():
            if isinstance(val, list):
                lines.append(f"  {key}:")
                for item in val:
                    if isinstance(item, dict):
                        lines.append(f"    Q: {item.get('q', '')}")
                        lines.append(f"    A: {item.get('a', '')}")
                    else:
                        lines.append(f"    - {item}")
            else:
                lines.append(f"  {key}: {val}")
        lines.append("")

    # Log entries
    lines.append("── LOG ENTRIES ──────────────────────────────────")
    lines.append("")

    for entry in bundle.entries:
        ts = entry.timestamp
        level = entry.level.value.upper().ljust(7)
        cat = entry.category.ljust(10)
        dur = f" ({entry.duration_ms:.0f}ms)" if entry.duration_ms else ""
        file_tag = f" [{entry.code_file}]" if entry.code_file else ""

        lines.append(f"[{ts}] {level} {cat} {entry.event}{dur}{file_tag}")

        if entry.detail:
            for dk, dv in entry.detail.items():
                val_str = str(dv)
                if len(val_str) > 300:
                    val_str = val_str[:300] + "…"
                lines.append(f"    {dk}: {val_str}")

        lines.append("")

    lines.append("=" * 72)
    lines.append("  END OF LOG")
    lines.append("=" * 72)

    return "\n".join(lines)


def export_global_txt() -> str:
    """Export all global logs as formatted text."""
    lines = [
        "=" * 72,
        "  IKSHAN SANDBOX — GLOBAL LOG EXPORT",
        f"  Exported: {datetime.utcnow().isoformat()}Z",
        f"  Total entries: {len(_global_log)}",
        f"  Sessions tracked: {len(_log_store)}",
        "=" * 72,
        "",
    ]

    for entry in _global_log:
        ts = entry.timestamp
        sid = entry.session_id[:8] if entry.session_id else "------"
        level = entry.level.value.upper().ljust(7)
        cat = entry.category.ljust(10)
        dur = f" ({entry.duration_ms:.0f}ms)" if entry.duration_ms else ""

        lines.append(f"[{ts}] [{sid}] {level} {cat} {entry.event}{dur}")

        if entry.detail:
            for dk, dv in entry.detail.items():
                val_str = str(dv)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "…"
                lines.append(f"    {dk}: {val_str}")

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)
