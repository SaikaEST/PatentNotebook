import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db_session
from app.models.entities import SourceDocument
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.citations import build_citations
from app.services.deepseek_client import DeepSeekError, generate_answer
from app.services.retrieval import retrieve_chunks

router = APIRouter()

_ASTERISK_PATTERN = re.compile(r"\*+")


def _build_source_lookup(sources: list[SourceDocument]) -> dict[str, dict[str, str | None]]:
    lookup: dict[str, dict[str, str | None]] = {}
    for source in sources:
        meta = source.meta_json or {}
        file_name = str(meta.get("file_name") or "").strip() or None
        lookup[str(source.id)] = {"source_name": file_name or source.doc_type}
    return lookup


def _sanitize_answer(answer: str) -> str:
    return _ASTERISK_PATTERN.sub("", answer)


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    if not payload.source_ids:
        return ChatResponse(
            answer="???????????????????",
            citations=[],
            missing=True,
            missing_reason="No sources selected",
        )

    sources = db.query(SourceDocument).filter(SourceDocument.id.in_(payload.source_ids)).all()
    source_lookup = _build_source_lookup(sources)

    results = retrieve_chunks(db, payload.source_ids, payload.question, top_k=8)
    chunks = [chunk for chunk, _ in results]

    if not chunks:
        return ChatResponse(
            answer="??????????????????? OCR?",
            citations=[],
            missing=True,
            missing_reason="No processed chunks available",
        )

    citations = build_citations(chunks, source_lookup=source_lookup)

    try:
        answer = generate_answer(payload.question, chunks, source_lookup)
    except DeepSeekError:
        excerpts = "\n".join([f"- {citation.quote}" for citation in citations])
        answer = "DeepSeek ??????????????????\n" + excerpts

    return ChatResponse(
        answer=_sanitize_answer(answer),
        citations=citations,
        missing=False,
        missing_reason=None,
    )
