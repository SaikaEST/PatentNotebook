from typing import List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import DocumentChunk
from app.services.vectorizer import embed_text


def retrieve_chunks(
    db: Session,
    source_ids: List[str],
    query: str,
    top_k: int = 5,
) -> List[Tuple[DocumentChunk, float]]:
    if not source_ids:
        return []

    query_vec = embed_text(query, settings.vector_dim)

    q = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.source_id.in_(source_ids))
        .filter(DocumentChunk.embedding.isnot(None))
        .order_by(DocumentChunk.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    rows = q.all()
    if rows:
        return [(row, 0.0) for row in rows]

    fallback = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.source_id.in_(source_ids))
        .order_by(DocumentChunk.chunk_index)
        .limit(top_k)
        .all()
    )
    return [(row, 0.0) for row in fallback]
