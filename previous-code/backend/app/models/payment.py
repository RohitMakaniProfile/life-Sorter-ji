"""
Payment models — JusPay order, webhook, and status schemas.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    """Request body for creating a JusPay payment order."""
    model_config = {"extra": "ignore"}
    amount: float = Field(..., description="Payment amount (e.g., 1000.00)")
    customer_id: str = Field(..., min_length=1, description="Unique customer identifier")
    customer_email: str = Field(default="", description="Customer email address")
    customer_phone: str = Field(default="", description="Customer phone number")
    return_url: str = Field(default="", description="Redirect URL after payment")
    description: str = Field(default="", description="Order description")
    udf1: str = Field(default="", description="User-defined field 1")
    udf2: str = Field(default="", description="User-defined field 2")


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
