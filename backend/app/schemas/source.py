from pydantic import BaseModel
from typing import Optional


class SourceDocumentCreate(BaseModel):
    jurisdiction_case_id: str
    doc_type: str
    language: Optional[str] = None
    source_type: Optional[str] = "upload"
    version: Optional[str] = None


class SourceDocumentOut(BaseModel):
    id: str
    doc_type: str
    language: Optional[str] = None
    source_type: Optional[str] = None
    included: bool
    file_uri: Optional[str] = None
