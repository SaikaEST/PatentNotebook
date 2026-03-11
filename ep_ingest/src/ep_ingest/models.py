from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


DocTypeNorm = Literal[
    "search_report",
    "search_opinion",
    "examination_communication",
    "applicant_response",
    "amendment",
    "grant_decision",
    "procedural_notice",
    "filing_document",
    "other",
]


class IdentifierMapping(BaseModel):
    publication_number: str | None = None
    application_number: str | None = None


class DocumentRecord(BaseModel):
    source: Literal["epo_register"] = "epo_register"
    register_document_id: str
    date: str | None = None
    document_type_raw: str
    procedure: str = ""
    pages: int = 0
    file_url: str
    content_type: Literal["pdf", "html"]
    local_path: str | None = None
    raw_text: str = ""
    doc_type_norm: DocTypeNorm = "other"


class TimelineEntry(BaseModel):
    date: str | None
    doc_type_norm: DocTypeNorm
    document_type_raw: str
    register_document_id: str


class PatentDataset(BaseModel):
    patent_id: str
    jurisdiction: Literal["EP"] = "EP"
    register_case_id: str
    identifiers: IdentifierMapping
    documents: list[DocumentRecord] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    generated_at: date | None = None
    metrics: dict[str, int] = Field(default_factory=dict)


class NormalizedIdentifier(BaseModel):
    normalized: str
    kind: Literal["publication", "application", "unknown"]
    publication_number: str | None = None
    application_number: str | None = None

    @property
    def patent_id(self) -> str:
        return f"EP:{self.normalized}"
