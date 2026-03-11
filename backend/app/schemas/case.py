from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PatentCaseCreate(BaseModel):
    title: Optional[str] = None
    family_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    application_no: Optional[str] = None
    publication_no: Optional[str] = None
    family_strategy: Optional[str] = None


class PatentCaseOut(BaseModel):
    id: str
    title: Optional[str] = None
    status: str
    jurisdiction_case_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    publication_no: Optional[str] = None
    application_no: Optional[str] = None


class IngestRequest(BaseModel):
    providers: List[str] = Field(default_factory=list)
    prefer_official: bool = True
    include_dms_fallback: bool = True
    trigger_processing: bool = True


class IngestResponse(BaseModel):
    status: str
    case_id: str
    task_id: str
    missing: bool = False
    missing_reason: Optional[str] = None
    followup_suggestions: List[str] = Field(default_factory=list)
    task_options: Dict[str, Any] = Field(default_factory=dict)


class IngestTaskStatusResponse(BaseModel):
    task_id: str
    state: str
    status: str
    stage: Optional[str] = None
    message: Optional[str] = None
    current: int = 0
    total: int = 0
    percent: int = 0
    case_id: Optional[str] = None
    created_sources: int = 0
    missing: bool = False
    missing_reason: Optional[str] = None
    followup_suggestions: List[str] = Field(default_factory=list)
