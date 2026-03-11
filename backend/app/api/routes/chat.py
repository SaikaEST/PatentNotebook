from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.retrieval import retrieve_chunks
from app.services.citations import build_citations

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db_session), user=Depends(get_current_user)):
    if not payload.source_ids:
        return ChatResponse(
            answer="Sources missing. Please upload or select source documents.",
            citations=[],
            missing=True,
            missing_reason="No sources selected",
        )

    results = retrieve_chunks(db, payload.source_ids, payload.question, top_k=5)
    chunks = [c for c, _ in results]

    if not chunks:
        return ChatResponse(
            answer="No relevant chunks available. Please ingest sources first.",
            citations=[],
            missing=True,
            missing_reason="No processed chunks available",
        )

    citations = build_citations(chunks)
    excerpts = "\n".join([f"- {c.quote}" for c in citations])
    answer = (
        "Relevant excerpts from sources:\n" + excerpts
    )

    return ChatResponse(
        answer=answer,
        citations=citations,
        missing=False,
        missing_reason=None,
    )
