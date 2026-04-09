from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStreamStartRequest(BaseModel):
    """Start (or resume) a background task stream for an actor."""

    onboarding_id: Optional[str] = Field(default=None, description="Onboarding actor id")
    user_id: Optional[str] = Field(default=None, description="Authenticated actor id (if available)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task-specific input payload")
    resume_if_exists: bool = Field(
        default=True,
        description="If a stream already exists for this task+actor, return the same stream_id instead of starting a new task.",
    )
    force_fresh: bool = Field(
        default=False,
        description="Cancel any existing stream for this task+actor and start a new one. Takes precedence over resume_if_exists.",
    )


class TaskStreamStartResponse(BaseModel):
    stream_id: str
    status: str


class TaskStreamAttachResponse(BaseModel):
    stream_id: str
    status: str


class TaskStreamActor(BaseModel):
    onboarding_id: Optional[str] = None
    user_id: Optional[str] = None

