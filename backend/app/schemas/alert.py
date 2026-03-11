from pydantic import BaseModel


class AlertSubscribeRequest(BaseModel):
    case_id: str
    channel: str
    target: str
