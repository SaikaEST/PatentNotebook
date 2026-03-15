import uuid
from typing import Callable, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.models.entities import DocumentChunk, JurisdictionCase, SourceDocument
from app.schemas.source import (
    SourceChunkOut,
    SourceDocumentOut,
    SourceProcessRequest,
    SourceProcessResponse,
    SourceViewerResponse,
)
from app.services.document_classifier import classify_doc_type, should_auto_include
from app.services.storage import storage_client
from app.tasks.ingest import ocr_source, process_source

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


def _to_source_out(source: SourceDocument) -> SourceDocumentOut:
    meta = source.meta_json or {}
    file_name = str(meta.get("file_name") or "").strip() or None
    return SourceDocumentOut(
        id=str(source.id),
        doc_type=classify_doc_type(
            raw_label=str(meta.get("document_type_raw") or source.doc_type),
            file_name=file_name,
            fallback=source.doc_type,
        ),
        file_name=file_name,
        language=source.language,
        source_type=source.source_type,
        included=source.included,
        file_uri=source.file_uri,
    )


def _select_sources(db: Session, payload: SourceProcessRequest) -> list[SourceDocument]:
    query = db.query(SourceDocument)
    source_ids = [item for item in dict.fromkeys(payload.source_ids) if item]

    if source_ids:
        query = query.filter(SourceDocument.id.in_(source_ids))
    elif payload.jurisdiction_case_id:
        resolved_jurisdiction_case_id = _resolve_jurisdiction_case_id(db, payload.jurisdiction_case_id)
        query = query.filter(SourceDocument.jurisdiction_case_id == resolved_jurisdiction_case_id)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide source_ids or jurisdiction_case_id to queue processing",
        )

    if payload.included_only:
        query = query.filter(SourceDocument.included.is_(True))

    sources = query.all()
    if not sources:
        raise HTTPException(status_code=404, detail="No matching sources found")
    return sources


def _queue_source_tasks(
    sources: list[SourceDocument],
    queue_task: Callable[[str], object],
) -> SourceProcessResponse:
    queued_source_ids: list[str] = []
    task_ids: list[str] = []
    for source in sources:
        task = queue_task(str(source.id))
        queued_source_ids.append(str(source.id))
        task_ids.append(task.id)

    return SourceProcessResponse(
        queued_count=len(queued_source_ids),
        queued_source_ids=queued_source_ids,
        task_ids=task_ids,
    )


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

    normalized_doc_type = classify_doc_type(raw_label=doc_type, file_name=file.filename, fallback=doc_type)
    source = SourceDocument(
        jurisdiction_case_id=resolved_jurisdiction_case_id,
        doc_type=normalized_doc_type,
        language=language,
        version=version,
        file_uri=file_uri,
        source_type="upload",
        meta_json={"file_name": file.filename},
        included=should_auto_include(normalized_doc_type),
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    process_source.delay(str(source.id))
    return _to_source_out(source)


@router.post("/process", response_model=SourceProcessResponse)
def queue_sources_processing(
    payload: SourceProcessRequest = Body(default_factory=SourceProcessRequest),
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    return _queue_source_tasks(_select_sources(db, payload), process_source.delay)


@router.post("/ocr", response_model=SourceProcessResponse)
def queue_sources_ocr(
    payload: SourceProcessRequest = Body(default_factory=SourceProcessRequest),
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    return _queue_source_tasks(_select_sources(db, payload), ocr_source.delay)


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
    return [_to_source_out(source) for source in query.all()]


@router.get("/{source_id}/viewer", response_model=SourceViewerResponse)
def get_source_viewer(
    source_id: str,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    source = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.source_id == source.id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    meta = source.meta_json or {}
    file_name = str(meta.get("file_name") or "").strip() or None
    return SourceViewerResponse(
        source_id=str(source.id),
        file_name=file_name,
        doc_type=classify_doc_type(
            raw_label=str(meta.get("document_type_raw") or source.doc_type),
            file_name=file_name,
            fallback=source.doc_type,
        ),
        language=source.language,
        source_type=source.source_type,
        file_uri=source.file_uri,
        text_uri=source.text_uri,
        chunks=[
            SourceChunkOut(
                id=str(chunk.id),
                chunk_index=chunk.chunk_index,
                page_no=chunk.page_no,
                text=chunk.text,
            )
            for chunk in chunks
        ],
    )


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


@router.post("/{source_id}/process")
def queue_source_processing(
    source_id: str,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    source = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    task = process_source.delay(str(source.id))
    return {"source_id": str(source.id), "task_id": task.id, "queued": True}


@router.post("/{source_id}/ocr")
def queue_source_ocr(
    source_id: str,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    source = db.query(SourceDocument).filter(SourceDocument.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    task = ocr_source.delay(str(source.id))
    return {"source_id": str(source.id), "task_id": task.id, "queued": True}

