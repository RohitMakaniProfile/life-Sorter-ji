"""
Company models — schemas for company search and listing.
"""

from typing import Optional, List

from pydantic import BaseModel, Field


class Company(BaseModel):
    """A company/startup record."""
    name: str
    country: str = ""
    problem: str = ""
    description: str = ""
    differentiator: str = ""
    aiAdvantage: str = ""
    fundingAmount: str = ""
    fundingDate: str = ""
    pricing: str = ""
    domain: str = ""
    rowNumber: int = 0
    matchScore: Optional[int] = None
    matchReason: Optional[str] = None


class UserContext(BaseModel):
    """User profile context for search personalization."""
    role: Optional[str] = None
    businessType: Optional[str] = None
    industry: Optional[str] = None
    targetAudience: Optional[str] = None
    marketSegment: Optional[str] = None
    roleAndIndustry: Optional[str] = None
    solutionFor: Optional[str] = None
    salaryContext: Optional[str] = None
    freelanceType: Optional[str] = None
    challenge: Optional[str] = None


class CompanySearchRequest(BaseModel):
    """Request body for AI-powered company search."""
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    requirement: Optional[str] = None
    userContext: Optional[UserContext] = None


class CompanySearchResponse(BaseModel):
    """Response from the company search endpoint."""
    success: bool
    companies: List[Company] = Field(default_factory=list)
    alternatives: Optional[List[Company]] = None
    totalCount: Optional[int] = None
    searchMethod: Optional[str] = None
    helpfulResponse: Optional[str] = None
    userRequirement: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class CompanyListResponse(BaseModel):
    """Response from the company listing endpoint."""
    success: bool
    count: int = 0
    companies: List[Company] = Field(default_factory=list)
    error: Optional[str] = None

# Force Pydantic to resolve types immediately for Python 3.13
Company.model_rebuild()
UserContext.model_rebuild()
CompanySearchRequest.model_rebuild()
CompanySearchResponse.model_rebuild()
CompanyListResponse.model_rebuild()