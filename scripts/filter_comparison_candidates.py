from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("amended_claims_with_annotations", ("amended claims with annotations",)),
    ("amended_description_with_annotations", ("amended description with annotations",)),
    ("text_intended_for_grant_clean_copy", ("text intended for grant clean copy",)),
    ("european_search_opinion", ("european search opinion",)),
    ("claims", ("claims",)),
    ("description", ("description",)),
]

CLAIMS_TRANSLATION_HINTS = (
    "translation of claims",
    "translation of the claims",
    "translations of the claims",
    "filing of the translations of the claims",
    "claims translation",
    "translated claims",
)
DESCRIPTION_TRANSLATION_HINTS = (
    "translation of description",
    "translation of the description",
    "translations of the description",
    "filing of the translations of the description",
    "description translation",
    "translated description",
)


def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_category(document_type_raw: str, file_name: str) -> str | None:
    text = normalize_text(f"{document_type_raw} {file_name}")
    for category, keywords in CATEGORY_RULES:
        if category == "claims":
            if not re.search(r"\bclaims\b", text):
                continue
        elif category == "description":
            if not re.search(r"\bdescription\b", text):
                continue
        elif not any(keyword in text for keyword in keywords):
            continue

        if category == "claims" and any(hint in text for hint in CLAIMS_TRANSLATION_HINTS):
            continue
        if category == "description" and any(hint in text for hint in DESCRIPTION_TRANSLATION_HINTS):
            continue
        return category
    return None


def resolve_source_path(local_path: str, file_name: str, out_root: Path) -> Path | None:
    local_path = (local_path or "").strip()
    if local_path:
        direct = Path(local_path)
        if direct.exists() and direct.is_file():
            return direct

        normalized = local_path.replace("\\", "/")
        marker = "/data/"
        rel_after_data = ""
        idx = normalized.lower().find(marker)
        if idx >= 0:
            rel_after_data = normalized[idx + len(marker) :]
        elif normalized.lower().startswith("/data"):
            rel_after_data = normalized[6:].lstrip("/")
        if rel_after_data:
            mapped = out_root / Path(*[p for p in rel_after_data.split("/") if p])
            if mapped.exists() and mapped.is_file():
                return mapped

    if file_name:
        matches = [p for p in out_root.rglob(file_name) if p.is_file()]
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    return None


def unique_target_path(target_dir: Path, file_name: str) -> Path:
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix
    candidate = target_dir / file_name
    if not candidate.exists():
        return candidate
    idx = 2
    while True:
        candidate = target_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def process_documents_json(documents_json: Path, out_root: Path) -> int:
    payload = json.loads(documents_json.read_text(encoding="utf-8"))
    documents = payload.get("documents") or []
    if not isinstance(documents, list):
        return 0

    files_dir = documents_json.parent / "files"
    comparison_dir = files_dir / "comparison_candidates"
    reset_comparison_dir(comparison_dir)

    selected: list[dict[str, str]] = []
    seen: set[Path] = set()

    for doc in documents:
        if not isinstance(doc, dict):
            continue
        file_name = str(doc.get("local_path") or "").strip()
        if file_name:
            file_name = Path(file_name).name
        if not file_name:
            file_name = str(doc.get("register_document_id") or "").strip()
        source = resolve_source_path(str(doc.get("local_path") or ""), file_name, out_root)
        if source is None or source in seen:
            continue

        category = match_category(str(doc.get("document_type_raw") or ""), source.name)
        if not category:
            continue

        target_dir = comparison_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_target_path(target_dir, source.name)
        shutil.copy2(source, target)
        seen.add(source)
        selected.append(
            {
                "category": category,
                "source_path": str(source),
                "target_path": str(target),
                "document_type_raw": str(doc.get("document_type_raw") or ""),
                "file_name": source.name,
            }
        )

    manifest = {
        "selected_count": len(selected),
        "categories": sorted({item["category"] for item in selected}),
        "files": selected,
    }
    (comparison_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return len(selected)


def reset_comparison_dir(comparison_dir: Path) -> None:
    if comparison_dir.exists():
        shutil.rmtree(comparison_dir)
    comparison_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build comparison_candidates folders from downloaded EP documents.json files.",
    )
    parser.add_argument("--out-root", default="data", help="Root folder containing EP_* directories.")
    args = parser.parse_args()

    out_root = Path(args.out_root).resolve()
    if not out_root.exists():
        print(f"out root not found: {out_root}")
        return

    total = 0
    datasets = 0
    for documents_json in out_root.rglob("documents.json"):
        count = process_documents_json(documents_json, out_root)
        if count > 0:
            datasets += 1
            total += count
            print(f"{documents_json}: selected={count}")
    print(f"done. datasets={datasets}, selected_files={total}")


if __name__ == "__main__":
    main()
