from __future__ import annotations

import re
from typing import Optional

DOCUMENT_CATEGORY_ORDER: tuple[str, ...] = (
    "communication_from_examining_division",
    "annex_to_the_communication",
    "reply_to_communication_from_examining_division",
    "amended_claims",
    "amended_claims_with_annotations",
    "claims",
    "european_search_opinion",
    "other",
)

_CLAIMS_TRANSLATION_HINTS = (
    "translation of claims",
    "translation of the claims",
    "translations of the claims",
    "filing of the translations of the claims",
    "claims translation",
    "translated claims",
    "translation of amended claims",
    "translation of the amended claims",
    "translations of the amended claims",
    "amended claims translation",
    "translated amended claims",
)


def _normalize_text(*values: Optional[str]) -> str:
    text = " ".join(value or "" for value in values).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_doc_type(
    *,
    raw_label: Optional[str] = None,
    file_name: Optional[str] = None,
    fallback: str = "other",
) -> str:
    text = _normalize_text(raw_label, file_name)
    if not text:
        return fallback or "other"

    if "reply to communication from the examining division" in text:
        return "reply_to_communication_from_examining_division"
    if "communication from the examining division" in text:
        return "communication_from_examining_division"
    if "annex to the communication" in text:
        return "annex_to_the_communication"
    if "amended claims with annotations" in text:
        if not any(hint in text for hint in _CLAIMS_TRANSLATION_HINTS):
            return "amended_claims_with_annotations"
    if "amended claims" in text:
        if not any(hint in text for hint in _CLAIMS_TRANSLATION_HINTS):
            return "amended_claims"
    if "european search opinion" in text:
        return "european_search_opinion"

    if re.search(r"\bclaims\b", text):
        if not any(hint in text for hint in _CLAIMS_TRANSLATION_HINTS):
            return "claims"

    normalized_fallback = (fallback or "other").strip().lower()
    if normalized_fallback in DOCUMENT_CATEGORY_ORDER:
        return normalized_fallback
    return "other"


def infer_doc_type(file_name: Optional[str], fallback: str = "other") -> str:
    return classify_doc_type(file_name=file_name, fallback=fallback)


def should_auto_include(doc_type: Optional[str]) -> bool:
    return (doc_type or "other").strip().lower() != "other"
