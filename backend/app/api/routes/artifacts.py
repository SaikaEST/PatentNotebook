import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.core.config import settings
from app.models.entities import Artifact
from app.schemas.artifact import ArtifactRequest, ArtifactResponse
from app.services.storage import storage_client
from app.tasks.artifacts import generate_artifact

router = APIRouter()


@router.post("/artifacts", response_model=ArtifactResponse)
def create_artifact(payload: ArtifactRequest, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    artifact = Artifact(
        id=uuid.uuid4(),
        case_id=payload.case_id,
        type=payload.artifact_type,
        status="queued",
        meta_json={"source_ids": payload.source_ids or [], **(payload.params or {})},
    )
    db.add(artifact)
    db.commit()

    generate_artifact.delay(str(artifact.id))

    return ArtifactResponse(
        artifact_id=str(artifact.id),
        status=artifact.status,
        output_uri=None,
        citations=[],
        missing=True,
        missing_reason="Artifact pending processing",
    )


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        return {"error": "not found"}
    return {
        "id": str(artifact.id),
        "status": artifact.status,
        "output_uri": artifact.output_uri,
        "type": artifact.type,
    }


@router.get("/artifacts/{artifact_id}/download-url")
def get_artifact_download_url(
    artifact_id: str,
    expires_in: int = Query(default=3600, ge=60, le=86400),
    db: Session = Depends(get_db_session),
    user=Depends(get_current_user),
):
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.status != "ready":
        raise HTTPException(status_code=409, detail="Artifact is not ready yet")
    if not artifact.output_uri:
        raise HTTPException(status_code=404, detail="Artifact output is missing")

    try:
        bucket, object_name = storage_client.parse_object_uri(artifact.output_uri)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsupported artifact output URI format")

    if bucket != settings.minio_bucket:
        raise HTTPException(status_code=400, detail="Artifact output bucket mismatch")

    url = storage_client.presigned_get_url(object_name, expires_in_seconds=expires_in)
    return {"artifact_id": str(artifact.id), "url": url, "expires_in": expires_in}
