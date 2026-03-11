from typing import Optional, List
from pydantic import BaseModel
from app.schemas.common import Citation


class ChatRequest(BaseModel):
    case_id: str
    question: str
    source_ids: Optional[List[str]] = None
    include_notes_as_sources: bool = False


class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    missing: bool = False
    missing_reason: Optional[str] = None
