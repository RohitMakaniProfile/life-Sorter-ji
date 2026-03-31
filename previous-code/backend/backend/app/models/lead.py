"""
Lead models — schemas for lead management and scoring.
"""



from typing import Any, Optional

from pydantic import BaseModel, Field


class LeadCreate(BaseModel):
    """Request body for creating a new lead."""
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    outcome_seeked: Optional[str] = None
    individual_type: Optional[str] = None
    persona: Optional[str] = None
    nature_of_business: Optional[str] = None
    business_website: Optional[str] = None
    manual_business_details: Optional[str] = None
    problem_description: Optional[str] = None
    micro_solutions_tried: Optional[bool] = None
    micro_solutions_details: Optional[str] = None
    tech_competency_level: Optional[int] = Field(default=3, ge=1, le=5)
    timeline_urgency: Optional[str] = None
    problem_due_to_poor_management: Optional[bool] = None
    ai_recommendations: Optional[list[dict]] = None


class LeadUpdate(BaseModel):
    """Request body for updating a lead (all fields optional)."""
    name: Optional[str] = None
    email: Optional[str] = None
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    outcome_seeked: Optional[str] = None
    individual_type: Optional[str] = None
    persona: Optional[str] = None
    nature_of_business: Optional[str] = None
    business_website: Optional[str] = None
    manual_business_details: Optional[str] = None
    problem_description: Optional[str] = None
    micro_solutions_tried: Optional[bool] = None
    micro_solutions_details: Optional[str] = None
    tech_competency_level: Optional[int] = Field(default=None, ge=1, le=5)
    timeline_urgency: Optional[str] = None
    problem_due_to_poor_management: Optional[bool] = None
    ai_recommendations: Optional[list[dict]] = None
    status: Optional[str] = None


class LeadResponse(BaseModel):
    """Response for a single lead operation."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class LeadListResponse(BaseModel):
    """Response for listing leads."""
    success: bool
    data: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    error: Optional[str] = None


class ConversationCreate(BaseModel):
    """Request body for saving a conversation."""
    messages: list[dict[str, Any]]
    recommendations: Optional[list[dict[str, Any]]] = None
