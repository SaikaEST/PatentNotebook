from typing import Optional
from pydantic import BaseModel


class Citation(BaseModel):
    source_id: str
    chunk_id: str
    page: Optional[int] = None
    quote: str
    source_name: Optional[str] = None
    viewer_url: Optional[str] = None


class MissingInfo(BaseModel):
    missing: bool = False
    missing_reason: Optional[str] = None
    followup_suggestions: Optional[list[str]] = None
