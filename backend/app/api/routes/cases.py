import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.models.entities import JurisdictionCase, PatentCase
from app.schemas.case import (
    IngestRequest,
    IngestResponse,
    IngestTaskStatusResponse,
    PatentCaseCreate,
    PatentCaseOut,
)
from app.tasks.celery_app import celery_app
from app.tasks.ingest import ingest_case

router = APIRouter()


@router.post("", response_model=PatentCaseOut)
def create_case(
    payload: PatentCaseCreate,
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    jurisdiction_case_id = None
    jurisdiction = None
    publication_no = None
    application_no = None

    case = PatentCase(
        tenant_id=user.tenant_id,
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        family_id=payload.family_id,
        title=payload.title,
        status="active",
        created_by=user.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    if payload.jurisdiction:
        juris = JurisdictionCase(
            case_id=case.id,
            jurisdiction=payload.jurisdiction,
            application_no=payload.application_no,
            publication_no=payload.publication_no,
        )
        db.add(juris)
        db.commit()
        db.refresh(juris)
        jurisdiction_case_id = str(juris.id)
        jurisdiction = juris.jurisdiction
        publication_no = juris.publication_no
        application_no = juris.application_no

    return PatentCaseOut(
        id=str(case.id),
        title=case.title,
        status=case.status,
        jurisdiction_case_id=jurisdiction_case_id,
        jurisdiction=jurisdiction,
        publication_no=publication_no,
        application_no=application_no,
    )


@router.get("")
def list_cases(db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    cases = db.query(PatentCase).filter(PatentCase.tenant_id == user.tenant_id).all()
    result = []
    for case in cases:
        jurisdiction_case = (
            db.query(JurisdictionCase)
            .filter(JurisdictionCase.case_id == case.id)
            .order_by(JurisdictionCase.created_at.asc())
            .first()
        )
        result.append(
            PatentCaseOut(
                id=str(case.id),
                title=case.title,
                status=case.status,
                jurisdiction_case_id=str(jurisdiction_case.id) if jurisdiction_case else None,
                jurisdiction=jurisdiction_case.jurisdiction if jurisdiction_case else None,
                publication_no=jurisdiction_case.publication_no if jurisdiction_case else None,
                application_no=jurisdiction_case.application_no if jurisdiction_case else None,
            )
        )
    return result


@router.post("/{case_id}/ingest", response_model=IngestResponse)
def start_ingest(
    case_id: str,
    payload: IngestRequest = Body(default_factory=IngestRequest),
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid case id") from exc

    case = (
        db.query(PatentCase)
        .filter(PatentCase.id == case_uuid)
        .filter(PatentCase.tenant_id == user.tenant_id)
        .first()
    )
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    has_jurisdiction_case = (
        db.query(JurisdictionCase).filter(JurisdictionCase.case_id == case.id).first() is not None
    )
    normalized_case_id = str(case_uuid)
    options = payload.model_dump()
    task = ingest_case.delay(normalized_case_id, options)

    if has_jurisdiction_case:
        return IngestResponse(
            status="queued",
            case_id=normalized_case_id,
            task_id=task.id,
            missing=False,
            task_options=options,
        )

    return IngestResponse(
        status="queued",
        case_id=normalized_case_id,
        task_id=task.id,
        missing=True,
        missing_reason="No jurisdiction case found; ingest may not fetch external sources",
        followup_suggestions=[
            "Add at least one jurisdiction record with application/publication number.",
            "Or upload prosecution documents first via /sources/upload.",
        ],
        task_options=options,
    )


@router.get("/ingest-tasks/{task_id}", response_model=IngestTaskStatusResponse)
def get_ingest_task_status(
    task_id: str,
    user=Depends(get_current_user),
):
    result = celery_app.AsyncResult(task_id)
    state = result.state or "PENDING"
    progress = result.info if isinstance(result.info, dict) else {}

    if state == "SUCCESS":
        payload = result.result if isinstance(result.result, dict) else {}
        created_sources = int(payload.get("created_sources") or len(payload.get("created_source_ids", []) or []))
        return IngestTaskStatusResponse(
            task_id=task_id,
            state=state,
            status=str(payload.get("status") or "completed"),
            stage="completed",
            message="采集完成",
            current=max(1, created_sources),
            total=max(1, created_sources),
            percent=100,
            case_id=payload.get("case_id"),
            created_sources=created_sources,
            missing=bool(payload.get("missing", False)),
            missing_reason=payload.get("missing_reason"),
            followup_suggestions=list(payload.get("followup_suggestions", []) or []),
        )

    if state == "FAILURE":
        return IngestTaskStatusResponse(
            task_id=task_id,
            state=state,
            status="failed",
            stage="failed",
            message=str(result.result or "采集失败"),
            percent=100,
        )

    if state == "PROGRESS":
        current = int(progress.get("current") or 0)
        total = int(progress.get("total") or 0)
        percent = int(progress.get("percent") or (current * 100 / total if total else 0))
        return IngestTaskStatusResponse(
            task_id=task_id,
            state=state,
            status=str(progress.get("status") or "running"),
            stage=progress.get("stage"),
            message=progress.get("message"),
            current=current,
            total=total,
            percent=max(0, min(100, percent)),
            case_id=progress.get("case_id"),
            created_sources=int(progress.get("created_sources") or 0),
            missing=bool(progress.get("missing", False)),
            missing_reason=progress.get("missing_reason"),
            followup_suggestions=list(progress.get("followup_suggestions", []) or []),
        )

    return IngestTaskStatusResponse(
        task_id=task_id,
        state=state,
        status="queued",
        stage="queued",
        message="采集任务排队中",
    )
