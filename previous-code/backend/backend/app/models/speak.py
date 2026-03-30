"""
Text-to-Speech models.
"""



from pydantic import BaseModel, Field


class SpeakRequest(BaseModel):
    """Request body for the TTS endpoint."""
    text: str = Field(..., min_length=1, description="Text to convert to speech")
    language: str = Field(
        default="english",
        description="Target language: 'english' or 'hindi'",
    )
SpeakRequest.model_rebuild()