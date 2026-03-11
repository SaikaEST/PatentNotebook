from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_current_user
from app.schemas.export import ExportRequest
from app.tasks.exports import export_case

router = APIRouter()


@router.post("")
def export(payload: ExportRequest, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    task = export_case.delay(payload.case_id, payload.format)
    return {"status": "queued", "task_id": task.id}
