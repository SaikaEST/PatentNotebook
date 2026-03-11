from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_current_user
from app.schemas.alert import AlertSubscribeRequest

router = APIRouter()


@router.post("")
def subscribe_alert(payload: AlertSubscribeRequest, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    return {"status": "subscribed", "case_id": payload.case_id, "channel": payload.channel}
