from typing import Optional, List
from pydantic import BaseModel
from app.schemas.common import Citation


class ArtifactRequest(BaseModel):
    case_id: str
    artifact_type: str
    source_ids: Optional[List[str]] = None
    params: Optional[dict] = None


class ArtifactResponse(BaseModel):
    artifact_id: str
    status: str
    output_uri: Optional[str] = None
    citations: List[Citation]
    missing: bool = False
    missing_reason: Optional[str] = None
