from pydantic import BaseModel


class ExportRequest(BaseModel):
    case_id: str
    format: str
