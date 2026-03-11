import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.models.entities import JurisdictionCase, SourceDocument
from app.schemas.source import SourceDocumentOut
from app.services.storage import storage_client
from app.tasks.ingest import process_source

router = APIRouter()


def _resolve_jurisdiction_case_id(db: Session, raw_value: str) -> str:
    candidate = (raw_value or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="jurisdiction_case_id is required")

    try:
        case_uuid = uuid.UUID(candidate)
        jurisdiction_case = db.query(JurisdictionCase).filter(JurisdictionCase.id == case_uuid).first()
        if not jurisdiction_case:
            raise HTTPException(status_code=404, detail="Jurisdiction case not found")
        return str(jurisdiction_case.id)
    except ValueError:
        jurisdiction_case = (
            db.query(JurisdictionCase)
            .filter(
                or_(
                    JurisdictionCase.application_no == candidate,
                    JurisdictionCase.publication_no == candidate,
                )
            )
            .first()
        )
        if not jurisdiction_case:
            raise HTTPException(
                status_code=404,
                detail="Jurisdiction case not found. Provide UUID or valid application/publication number.",
            )
        return str(jurisdiction_case.id)


@router.post("/upload", response_model=SourceDocumentOut)
async def upload_source(
    jurisdiction_case_id: str = Form(...),
    doc_type: str = Form(...),
    language: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    resolved_jurisdiction_case_id = _resolve_jurisdiction_case_id(db, jurisdiction_case_id)
    object_name = f"{resolved_jurisdiction_case_id}/{uuid.uuid4()}_{file.filename}"
    storage_client.ensure_bucket()
    storage_client.put_object(object_name, file.file, file.content_type)
    file_uri = storage_client.object_uri(object_name)

    source = SourceDocument(
        jurisdiction_case_id=resolved_jurisdiction_case_id,
        doc_type=doc_type,
        language=language,
        version=version,
        file_uri=file_uri,
        source_type="upload",
        included=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    process_source.delay(str(source.id))

    return SourceDocumentOut(
        id=str(source.id),
        doc_type=source.doc_type,
        language=source.language,
        source_type=source.source_type,
        included=source.included,
        file_uri=source.file_uri,
    )


@router.get("")
def list_sources(
    jurisdiction_case_id: Optional[str] = None,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    query = db.query(SourceDocument)
    if jurisdiction_case_id:
        resolved_jurisdiction_case_id = _resolve_jurisdiction_case_id(db, jurisdiction_case_id)
        query = query.filter(SourceDocument.jurisdiction_case_id == resolved_jurisdiction_case_id)
    sources = query.all()
    return [
        SourceDocumentOut(
            id=str(src.id),
            doc_type=src.doc_type,
            language=src.language,
            source_type=src.source_type,
            included=src.included,
            file_uri=src.file_uri,
        )
        for src in sources
    ]


@router.patch("/{source_id}")
def update_source_include(
    source_id: str,
    included: bool,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    source = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.included = included
    db.commit()
    return {"id": source_id, "included": included}
