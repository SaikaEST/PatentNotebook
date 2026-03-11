from __future__ import annotations

from ep_ingest.models import DocumentRecord, TimelineEntry


def build_timeline(documents: list[DocumentRecord]) -> list[TimelineEntry]:
    entries = [
        TimelineEntry(
            date=doc.date,
            doc_type_norm=doc.doc_type_norm,
            document_type_raw=doc.document_type_raw,
            register_document_id=doc.register_document_id,
        )
        for doc in documents
    ]
    entries.sort(
        key=lambda item: (
            item.date or "9999-12-31",
            item.doc_type_norm,
            item.document_type_raw.lower(),
        )
    )
    return entries


def timeline_to_markdown(entries: list[TimelineEntry]) -> str:
    lines = [
        "| Date | Normalized Type | Register Type | Document ID |",
        "|---|---|---|---|",
    ]
    for entry in entries:
        lines.append(
            f"| {entry.date or ''} | {entry.doc_type_norm} | "
            f"{entry.document_type_raw} | {entry.register_document_id} |"
        )
    return "\n".join(lines) + "\n"
