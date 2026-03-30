from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# 1. No "from __future__ import annotations" at the top!

class Persona(str, Enum):
    PRODUCT = "product"
    CONTRIBUTOR = "contributor"
    ASSISTANT = "assistant"
    DEFAULT = "default"

class ConversationMessage(BaseModel):
    role: str = Field(..., description="Message role: 'user', 'assistant', or 'system'")
    content: str = Field(..., description="Message text content")

class ChatContext(BaseModel):
    generateBrief: bool = False
    isRedirecting: bool = False
    domain: Optional[str] = None
    subDomain: Optional[str] = None

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    persona: Persona = Persona.DEFAULT
    context: Optional[ChatContext] = None
    # We use List[ConversationMessage] directly so the generator sees the class
    conversationHistory: Optional[List[ConversationMessage]] = None
    stage: int = Field(default=1, ge=1, le=2)
    payment_order_id: Optional[str] = None

class ChatResponse(BaseModel):
    message: str
    usage: Optional[Dict[str, Any]] = None

# 2. Force the rebuild so the doc generator doesn't see "ForwardRef"
ChatRequest.model_rebuild()
ChatResponse.model_rebuild()