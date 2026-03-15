from typing import Any, List

from app.models.entities import DocumentChunk
from app.schemas.common import Citation


def build_citations(
    chunks: List[DocumentChunk],
    max_quote: int = 200,
    source_lookup: dict[str, dict[str, Any]] | None = None,
) -> List[Citation]:
    citations: List[Citation] = []
    for chunk in chunks:
        source_id = str(chunk.source_id)
        source_meta = (source_lookup or {}).get(source_id, {})
        quote = (chunk.text or "")[:max_quote]
        citations.append(
            Citation(
                source_id=source_id,
                chunk_id=str(chunk.id),
                page=chunk.page_no,
                quote=quote,
                source_name=str(source_meta.get("source_name") or "").strip() or None,
                viewer_url=f"/assistant/sources/{source_id}?chunk={chunk.id}",
            )
        )
    return citations
