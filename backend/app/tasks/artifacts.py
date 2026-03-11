import uuid
from sqlalchemy.orm import Session

from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.entities import Artifact, JurisdictionCase, SourceDocument, DocumentChunk
from app.services.retrieval import retrieve_chunks
from app.services.artifact_builder import build_artifact_markdown
from app.services.storage import storage_client


def _get_source_ids(db: Session, case_id: str, source_ids: list[str]) -> list[str]:
    if source_ids:
        return source_ids
    juris_ids = [
        str(j.id) for j in db.query(JurisdictionCase).filter(JurisdictionCase.case_id == case_id).all()
    ]
    if not juris_ids:
        return []
    sources = db.query(SourceDocument).filter(SourceDocument.jurisdiction_case_id.in_(juris_ids)).all()
    return [str(s.id) for s in sources]


@celery_app.task(name="app.tasks.artifacts.generate_artifact")
def generate_artifact(artifact_id: str):
    db = SessionLocal()
    try:
        aid = uuid.UUID(artifact_id)
        artifact = db.query(Artifact).filter(Artifact.id == aid).first()
        if not artifact:
            return {"status": "error", "reason": "artifact not found"}

        source_ids = artifact.meta_json.get("source_ids", []) if artifact.meta_json else []
        source_ids = _get_source_ids(db, str(artifact.case_id), source_ids)

        chunks = []
        if source_ids:
            chunks = [c for c, _ in retrieve_chunks(db, source_ids, artifact.type, top_k=5)]
        else:
            chunks = db.query(DocumentChunk).limit(5).all()

        markdown = build_artifact_markdown(artifact.type, chunks)
        object_name = f"artifacts/{artifact.id}.md"
        storage_client.put_text(object_name, markdown, content_type="text/markdown")
        artifact.output_uri = storage_client.object_uri(object_name)
        artifact.status = "ready"
        db.commit()

        return {"status": "ready", "artifact_id": str(artifact.id)}
    finally:
        db.close()
