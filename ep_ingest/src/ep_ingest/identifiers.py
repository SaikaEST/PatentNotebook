from __future__ import annotations

import re

from ep_ingest.models import NormalizedIdentifier

_PUB_RE = re.compile(r"^EP\d{7,}$")
_APP_RE = re.compile(r"^EP\d{8}\.\d$")
_APP_NO_PREFIX_RE = re.compile(r"^\d{8}\.\d$")
_PUB_NO_PREFIX_RE = re.compile(r"^\d{7,}$")


def normalize_identifier(value: str) -> NormalizedIdentifier:
    raw = re.sub(r"\s+", "", value).upper()
    if _APP_RE.fullmatch(raw):
        return NormalizedIdentifier(
            normalized=raw,
            kind="application",
            application_number=raw,
        )
    if _APP_NO_PREFIX_RE.fullmatch(raw):
        normalized = f"EP{raw}"
        return NormalizedIdentifier(
            normalized=normalized,
            kind="application",
            application_number=normalized,
        )
    if _PUB_RE.fullmatch(raw):
        return NormalizedIdentifier(
            normalized=raw,
            kind="publication",
            publication_number=raw,
        )
    if _PUB_NO_PREFIX_RE.fullmatch(raw):
        normalized = f"EP{raw}"
        return NormalizedIdentifier(
            normalized=normalized,
            kind="publication",
            publication_number=normalized,
        )
    if raw.startswith("EP") and "." in raw:
        return NormalizedIdentifier(
            normalized=raw,
            kind="application",
            application_number=raw,
        )
    if raw.startswith("EP"):
        return NormalizedIdentifier(
            normalized=raw,
            kind="publication",
            publication_number=raw,
        )
    return NormalizedIdentifier(normalized=raw, kind="unknown")
