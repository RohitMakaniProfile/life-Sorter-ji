"""
Payment models — JusPay order, webhook, and status schemas.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    """Request body for creating a JusPay payment order."""
    model_config = {"extra": "ignore"}
    amount: float = Field(
        default=0,
        description="Ignored when plan_slug is set (server uses catalog price). Kept for older clients.",
    )
    customer_id: str = Field(
        default="",
        description="Ignored for authenticated checkout; server sends JWT users.id to JusPay as customer_id.",
    )
    customer_email: str = Field(default="", description="Optional; server falls back to profile email")
    customer_phone: str = Field(default="", description="Optional; server falls back to profile phone")
    return_url: str = Field(default="", description="Redirect URL after payment")
    description: str = Field(default="", description="Order description (optional; defaults from plan name)")
    udf1: str = Field(default="", description="User-defined field 1")
    udf2: str = Field(default="", description="User-defined field 2")
    plan_slug: Optional[str] = Field(
        default=None,
        description="Catalog plan slug (e.g. deep_analysis_l1). Required; amount from plans; checkout bound to JWT user.",
    )


class CreateOrderResponse(BaseModel):
    """Response from order creation."""
    success: bool
    order_id: Optional[str] = None
    client_auth_token: Optional[str] = None
    status: Optional[str] = None
    payment_links: Optional[dict[str, Any]] = None
    sdk_payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    details: Optional[str] = None


class WebhookPayload(BaseModel):
    """JusPay webhook callback payload."""
    order_id: Optional[str] = None
    status: Optional[str] = None
    txn_id: Optional[str] = None
    amount: Optional[str] = None
    signature: Optional[str] = None
    signature_algorithm: Optional[str] = None

    class Config:
        extra = "allow"  # Allow extra fields from JusPay


class PaymentStatusResponse(BaseModel):
    """Response from order status check."""
    success: bool
    order_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[str] = None
    currency: str = "INR"
    customer_id: Optional[str] = None
    customer_email: Optional[str] = None
    txn_id: Optional[str] = None
    payment_method: Optional[str] = None
    payment_method_type: Optional[str] = None
    refunds: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class RefundRequest(BaseModel):
    """Request body for initiating a refund."""
    order_id: str = Field(..., description="JusPay order ID to refund")
    amount: Optional[str] = Field(default=None, description="Partial refund amount (full if omitted)")
    unique_request_id: Optional[str] = Field(default=None, description="Idempotency key")


class PaymentVerification(BaseModel):
    """Response from Stage 2 payment verification."""
    verified: bool
    order_id: Optional[str] = None
    amount: Optional[str] = None
    txn_id: Optional[str] = None
    reason: Optional[str] = None
    status: Optional[str] = None


class PaymentCompleteRequest(BaseModel):
    """Complete checkout: verify JusPay order and grant plan (user from JWT; plan bound at create-order)."""

    model_config = {"extra": "ignore"}
    order_id: str = Field(..., min_length=1, description="JusPay order_id to verify and redeem")


class CapabilityState(BaseModel):
    """Aggregated access for one product capability across all active grants."""

    allowed: bool
    unlimited: bool = False
    credits_remaining: Optional[int] = None
    via_admin_grant: bool = False


class PlanGrantSummary(BaseModel):
    plan_slug: str
    plan_name: str
    order_id: str
    credits_remaining: Optional[int] = None
    credits_unlimited: bool
    granted_at: Optional[str] = None
    features: dict[str, Any] = Field(default_factory=dict)
    # Admin grant specific fields
    is_admin_grant: bool = False
    granted_by_email: Optional[str] = None


class AdminGrantInfo(BaseModel):
    """Details about an admin-granted subscription."""
    id: str
    user_id: str
    granted_by_user_id: str
    granted_by_email: str = ""
    reason: str = ""
    is_active: bool
    granted_at: Optional[str] = None


class UserEntitlementsResponse(BaseModel):
    """Plans purchased by this authenticated user plus merged capabilities (credits; NULL pool = unlimited)."""

    user_id: str
    grants: list[PlanGrantSummary] = Field(default_factory=list)
    capabilities: dict[str, CapabilityState] = Field(default_factory=dict)
    has_admin_grant: bool = False
    admin_grant: Optional[AdminGrantInfo] = None


class PlanCatalogRow(BaseModel):
    """Public plan row for pricing UI."""

    id: str
    slug: str
    name: str
    description: str
    price_inr: float
    credits_allocation: Optional[int] = None
    features: dict[str, Any] = Field(default_factory=dict)
    display_order: int = 0
