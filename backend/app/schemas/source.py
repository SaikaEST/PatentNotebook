from typing import List, Optional

from pydantic import BaseModel, Field


class SourceDocumentCreate(BaseModel):
    jurisdiction_case_id: str
    doc_type: str
    language: Optional[str] = None
    source_type: Optional[str] = "upload"
    version: Optional[str] = None


class SourceDocumentOut(BaseModel):
    id: str
    doc_type: str
    file_name: Optional[str] = None
    language: Optional[str] = None
    source_type: Optional[str] = None
    included: bool
    file_uri: Optional[str] = None


class SourceChunkOut(BaseModel):
    id: str
    chunk_index: int
    page_no: Optional[int] = None
    text: str


class SourceViewerResponse(BaseModel):
    source_id: str
    file_name: Optional[str] = None
    doc_type: str
    language: Optional[str] = None
    source_type: Optional[str] = None
    file_uri: Optional[str] = None
    text_uri: Optional[str] = None
    chunks: List[SourceChunkOut] = Field(default_factory=list)


class SourceProcessRequest(BaseModel):
    jurisdiction_case_id: Optional[str] = None
    included_only: bool = True
    source_ids: List[str] = Field(default_factory=list)


class SourceProcessResponse(BaseModel):
    queued_count: int
    queued_source_ids: List[str] = Field(default_factory=list)
    task_ids: List[str] = Field(default_factory=list)
