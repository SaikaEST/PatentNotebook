from __future__ import annotations

import re

from ep_ingest.models import DocTypeNorm


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def classify_document(document_type_raw: str, raw_text: str) -> DocTypeNorm:
    label = (document_type_raw or "").strip()
    text_head = (raw_text or "")[:5000]
    combined = f"{label}\n{text_head}"

    if _contains_any(
        combined,
        [r"EUROPEAN SEARCH REPORT", r"\bEuropean search report\b"],
    ):
        return "search_report"
    if _contains_any(
        combined,
        [r"\bEuropean search opinion\b", r"\bwritten opinion\b"],
    ):
        return "search_opinion"
    if _contains_any(combined, [r"\bCommunication\b"]) and _contains_any(
        combined,
        [r"Article\s*94\(3\)", r"\bExamining Division\b", r"\bSummons\b"],
    ):
        return "examination_communication"
    if _contains_any(
        combined,
        [
            r"\bReply\b",
            r"\bResponse\b",
            r"Observations of the applicant",
            r"Letter from applicant",
        ],
    ):
        return "applicant_response"
    if _contains_any(
        combined,
        [
            r"\bAmendments\b",
            r"Replacement sheets",
            r"Correction of deficiencies",
            r"Rule\s*137",
        ],
    ):
        return "amendment"
    if _contains_any(
        combined,
        [r"Rule\s*71\(3\)", r"Decision to grant", r"Mention of the grant"],
    ):
        return "grant_decision"
    if _contains_any(
        combined,
        [
            r"\bReminder\b",
            r"Notification of forthcoming publication",
            r"transmission of the European search report",
            r"\bfee\b",
        ],
    ):
        return "procedural_notice"
    if _contains_any(
        combined,
        [
            r"\bClaims\b",
            r"\bDescription\b",
            r"\bDrawings\b",
            r"Request for grant",
            r"\bAbstract\b",
            r"Designation of inventor",
            r"Priority document",
        ],
    ):
        return "filing_document"
    return "other"
