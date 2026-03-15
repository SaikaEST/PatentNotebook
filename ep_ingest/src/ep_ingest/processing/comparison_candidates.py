from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ep_ingest.models import DocumentRecord


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("communication_from_examining_division", ("communication from the examining division",)),
    ("annex_to_the_communication", ("annex to the communication",)),
    ("reply_to_communication_from_examining_division", ("reply to communication from the examining division",)),
    ("amended_claims", ("amended claims",)),
    ("amended_claims_with_annotations", ("amended claims with annotations",)),
    ("european_search_opinion", ("european search opinion",)),
    ("claims", ("claims",)),
]

CLAIMS_TRANSLATION_HINTS = (
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


def export_comparison_candidates(
    documents: list[DocumentRecord],
    files_dir: Path,
) -> dict[str, Any]:
    comparison_dir = files_dir / "comparison_candidates"
    _reset_comparison_dir(comparison_dir)

    selected: list[dict[str, str]] = []
    seen_sources: set[Path] = set()

    for document in documents:
        source_path = _resolve_source_path(document.local_path or "", files_dir)
        if source_path is None or source_path in seen_sources:
            continue

        category = _match_category(
            document_type_raw=document.document_type_raw,
            file_name=source_path.name,
        )
        if not category:
            continue

        target_dir = comparison_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = _unique_target_path(target_dir, source_path.name)
        shutil.copy2(source_path, target_path)
        seen_sources.add(source_path)
        selected.append(
            {
                "category": category,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "document_type_raw": document.document_type_raw,
                "file_name": source_path.name,
            }
        )

    payload = {
        "selected_count": len(selected),
        "categories": sorted({item["category"] for item in selected}),
        "files": selected,
    }
    (comparison_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def _reset_comparison_dir(comparison_dir: Path) -> None:
    if comparison_dir.exists():
        shutil.rmtree(comparison_dir)
    comparison_dir.mkdir(parents=True, exist_ok=True)


def _resolve_source_path(local_path: str, files_dir: Path) -> Path | None:
    raw = local_path.strip()
    if raw:
        candidate = Path(raw)
        if candidate.exists() and candidate.is_file():
            return candidate

    if not files_dir.exists():
        return None

    file_name = Path(raw).name
    if not file_name:
        return None
    matches = [path for path in files_dir.rglob(file_name) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _match_category(*, document_type_raw: str, file_name: str) -> str | None:
    text = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", f"{document_type_raw} {file_name}".lower())).strip()

    if "reply to communication from the examining division" in text:
        return "reply_to_communication_from_examining_division"
    if "amended claims with annotations" in text:
        return "amended_claims_with_annotations"

    for category, keywords in CATEGORY_RULES:
        if category == "claims":
            if not re.search(r"\bclaims\b", text):
                continue
        elif not any(keyword in text for keyword in keywords):
            continue

        if "claims" in category and any(hint in text for hint in CLAIMS_TRANSLATION_HINTS):
            continue
        return category
    return None


def _unique_target_path(target_dir: Path, file_name: str) -> Path:
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix
    candidate = target_dir / file_name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        candidate = target_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1







