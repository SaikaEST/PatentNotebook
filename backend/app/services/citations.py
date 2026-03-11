from typing import List

from app.schemas.common import Citation
from app.models.entities import DocumentChunk


def build_citations(chunks: List[DocumentChunk], max_quote: int = 200) -> List[Citation]:
    citations: List[Citation] = []
    for chunk in chunks:
        quote = (chunk.text or "")[:max_quote]
        citations.append(
            Citation(
                source_id=str(chunk.source_id),
                chunk_id=str(chunk.id),
                page=chunk.page_no,
                quote=quote,
            )
        )
    return citations
