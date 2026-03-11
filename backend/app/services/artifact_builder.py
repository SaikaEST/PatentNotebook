from typing import List

from app.models.entities import DocumentChunk
from app.services.citations import build_citations


def build_artifact_markdown(artifact_type: str, chunks: List[DocumentChunk]) -> str:
    citations = build_citations(chunks)
    citation_lines = [
        f"- {c.source_id}:{c.page} {c.quote}" for c in citations
    ]
    citations_block = "\n".join(citation_lines) if citation_lines else "- missing"

    if artifact_type == "timeline":
        return (
            "# Timeline\n\n"
            "## Key Events\n"
            "- missing (requires extracted events)\n\n"
            "## Evidence\n"
            f"{citations_block}\n"
        )
    if artifact_type == "claim_diff":
        return (
            "# Claim Diff\n\n"
            "## Independent Claim Changes\n"
            "- missing (requires claim extraction and diff)\n\n"
            "## Evidence\n"
            f"{citations_block}\n"
        )
    if artifact_type == "risk_report":
        return (
            "# Risk Report\n\n"
            "## Risk Signals\n"
            "- missing (requires issue/response analysis)\n\n"
            "## Evidence\n"
            f"{citations_block}\n"
        )

    return (
        "# Quick Outline\n\n"
        "## Basic Info\n"
        "- missing (requires metadata)\n\n"
        "## Core Issues\n"
        "- missing (requires issue extraction)\n\n"
        "## Evidence\n"
        f"{citations_block}\n"
    )
