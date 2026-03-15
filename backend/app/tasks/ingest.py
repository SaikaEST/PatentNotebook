import json
import shutil
import uuid
from io import BytesIO
from pathlib import Path
import re
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.entities import (
    DocumentChunk,
    JurisdictionCase,
    PatentCase,
    SourceDocument,
)
from app.pipelines.adapters.registry import ADAPTERS, resolve_provider_order
from app.services.document_classifier import classify_doc_type, infer_doc_type, should_auto_include
from app.services.document_parser import chunk_pages, parse_document_bytes
from app.services.storage import storage_client
from app.services.vectorizer import embed_text
from app.tasks.celery_app import celery_app

DEFAULT_INGEST_OPTIONS = {
    "providers": [],
    "prefer_official": True,
    "include_dms_fallback": True,
    "trigger_processing": True,
}

ProgressCallback = Callable[[dict[str, Any]], None]

_COMPARISON_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "communication_from_examining_division",
        ("communication from the examining division",),
    ),
    (
        "annex_to_the_communication",
        ("annex to the communication",),
    ),
    (
        "reply_to_communication_from_examining_division",
        ("reply to communication from the examining division",),
    ),
    (
        "amended_claims",
        ("amended claims",),
    ),
    (
        "amended_claims_with_annotations",
        ("amended claims with annotations",),
    ),
    (
        "european_search_opinion",
        ("european search opinion",),
    ),
    (
        "claims",
        ("claims",),
    ),
]
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

def _load_source_bytes(source: SourceDocument) -> tuple[bytes, dict[str, Any]]:
    metadata = source.meta_json or {}
    if source.file_uri:
        try:
            _, object_name = storage_client.parse_object_uri(source.file_uri)
            data = storage_client.get_object_bytes(object_name)
            return data, {"payload_source": "minio", "object_name": object_name}
        except Exception:
            pass

    local_path = str(metadata.get("local_path") or "").strip()
    if local_path:
        path = Path(local_path)
        if path.exists() and path.is_file():
            return path.read_bytes(), {"payload_source": "local_path", "local_path": str(path)}

    source_uri = str(metadata.get("source_uri") or "").strip()
    if source_uri and "://" not in source_uri:
        path = Path(source_uri)
        if path.exists() and path.is_file():
            return path.read_bytes(), {"payload_source": "source_uri_path", "local_path": str(path)}

    file_name = str(metadata.get("file_name") or "").strip()
    if file_name:
        search_root = Path(settings.ep_ingest_out_dir or "/data")
        if search_root.exists():
            matches = [p for p in search_root.rglob(file_name) if p.is_file()]
            if matches:
                latest = max(matches, key=lambda p: p.stat().st_mtime)
                return latest.read_bytes(), {"payload_source": "local_scan", "local_path": str(latest)}

    source_uri = str(metadata.get("source_uri") or "").strip()
    if source_uri:
        search_root = Path(settings.ep_ingest_out_dir or "/data")
        if search_root.exists():
            token = ""
            mode = ""
            uri_match = re.search(r"/([A-Za-z]{2})/(\d+)/([A-Za-z]\d?)/(fullimage|firstpage)$", source_uri)
            if uri_match:
                token = f"{uri_match.group(1)}{uri_match.group(2)}{uri_match.group(3)}".upper()
                mode = uri_match.group(4).lower()
            if not token and file_name:
                name_match = re.search(r"([A-Za-z]{2}\d+[A-Za-z]\d?)_(fullimage|firstpage)\.pdf$", file_name)
                if name_match:
                    token = name_match.group(1).upper()
                    mode = name_match.group(2).lower()
            if token:
                pattern = f"*{token}*{mode}*.pdf" if mode else f"*{token}*.pdf"
                matches = [p for p in search_root.rglob(pattern) if p.is_file()]
                if matches:
                    latest = max(matches, key=lambda p: p.stat().st_mtime)
                    return latest.read_bytes(), {"payload_source": "local_ops_scan", "local_path": str(latest)}

    raise RuntimeError("source payload unavailable in both MinIO and local_path")


def _build_metadata_fallback_text(source: SourceDocument) -> str:
    meta = source.meta_json or {}
    file_name = str(meta.get("file_name") or "").strip()
    source_uri = str(meta.get("source_uri") or source.file_uri or "").strip()
    local_path = str(meta.get("local_path") or "").strip()
    parts = [
        "No extractable text was found in this PDF (likely scanned/image-only). OCR is required for full content.",
        f"doc_type={source.doc_type}",
    ]
    if source.language:
        parts.append(f"language={source.language}")
    if file_name:
        parts.append(f"file_name={file_name}")
    if source_uri:
        parts.append(f"source_uri={source_uri}")
    if local_path:
        parts.append(f"local_path={local_path}")
    return "\n".join(parts)


def _resolve_local_text_output_path(source: SourceDocument, payload_meta: dict[str, Any]) -> Path | None:
    source_meta = source.meta_json or {}
    file_name = str(source_meta.get("file_name") or payload_meta.get("file_name") or "").strip()
    safe_text_name = Path(file_name).with_suffix(".txt").name if file_name else f"{source.id}.txt"
    current_local_text_path = str(source_meta.get("local_text_path") or "").strip()

    candidates = [
        str(payload_meta.get("local_path") or "").strip(),
        str(source_meta.get("local_path") or "").strip(),
    ]
    for raw in candidates:
        if not raw:
            continue
        source_path = Path(raw)
        parents = [source_path.parent, *source_path.parents]
        for parent in parents:
            if parent.name.lower() == "files":
                text_dir = parent.parent / "text"
                text_dir.mkdir(parents=True, exist_ok=True)
                candidate = text_dir / safe_text_name
                if candidate.exists() and current_local_text_path and Path(current_local_text_path) != candidate:
                    candidate = text_dir / f"{Path(safe_text_name).stem}_{source.id}.txt"
                return candidate
        text_dir = source_path.parent / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        candidate = text_dir / safe_text_name
        if candidate.exists() and current_local_text_path and Path(current_local_text_path) != candidate:
            candidate = text_dir / f"{Path(safe_text_name).stem}_{source.id}.txt"
        return candidate

    root = Path(settings.ep_ingest_out_dir or "/data")
    text_dir = root / "parsed_local"
    text_dir.mkdir(parents=True, exist_ok=True)
    candidate = text_dir / safe_text_name
    if candidate.exists() and current_local_text_path and Path(current_local_text_path) != candidate:
        candidate = text_dir / f"{Path(safe_text_name).stem}_{source.id}.txt"
    return candidate



def _write_local_text_copy(source: SourceDocument, payload_meta: dict[str, Any], text: str) -> str | None:
    output_path = _resolve_local_text_output_path(source, payload_meta)
    if output_path is None:
        return None
    try:
        output_path.write_text(text, encoding="utf-8")
    except Exception:
        return None
    return str(output_path)


def _persist_parsed_source(
    db: Session,
    source: SourceDocument,
    pages: list[dict[str, Any]],
    payload_meta: dict[str, Any],
    *,
    extraction_mode: str | None,
    fallback_extraction: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunks = list(chunk_pages(pages))
    db.query(DocumentChunk).filter(DocumentChunk.source_id == source.id).delete()

    updated_meta = {**(source.meta_json or {}), **payload_meta, "pages": len(pages)}
    if extra_meta:
        for key, value in extra_meta.items():
            if value is None:
                updated_meta.pop(key, None)
            else:
                updated_meta[key] = value

    if not chunks:
        # Keep a metadata-only placeholder until OCR or manual review enriches the source.
        fallback_text = _build_metadata_fallback_text(source)
        embedding = embed_text(fallback_text, settings.vector_dim)
        db.add(
            DocumentChunk(
                source_id=source.id,
                chunk_index=0,
                page_no=None,
                offset_start=None,
                offset_end=None,
                text=fallback_text,
                embedding=embedding,
            )
        )
        updated_meta["chunks"] = 1
        updated_meta["text_extraction"] = fallback_extraction
        source.text_uri = None
        local_text_path = _write_local_text_copy(source, payload_meta, fallback_text)
        if local_text_path:
            updated_meta["local_text_path"] = local_text_path
        else:
            updated_meta.pop("local_text_path", None)
        source.meta_json = updated_meta
        db.commit()
        return {"status": "ok", "chunks": 1, "fallback": "metadata_only"}

    for idx, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        if not text:
            continue
        embedding = embed_text(text, settings.vector_dim)
        db.add(
            DocumentChunk(
                source_id=source.id,
                chunk_index=idx,
                page_no=chunk.get("page_no"),
                offset_start=None,
                offset_end=None,
                text=text,
                embedding=embedding,
            )
        )

    full_text = "\n".join([c.get("text", "") for c in chunks])
    text_object = f"parsed/{source.id}.txt"
    storage_client.put_text(text_object, full_text)
    source.text_uri = storage_client.object_uri(text_object)
    local_text_path = _write_local_text_copy(source, payload_meta, full_text)
    if local_text_path:
        updated_meta["local_text_path"] = local_text_path
    else:
        updated_meta.pop("local_text_path", None)
    updated_meta["chunks"] = len(chunks)
    if extraction_mode:
        updated_meta["text_extraction"] = extraction_mode
    else:
        updated_meta.pop("text_extraction", None)
    source.meta_json = updated_meta

    db.commit()
    return {"status": "ok", "chunks": len(chunks)}


def _queue_ocr_task(db: Session, source: SourceDocument) -> str:
    task = ocr_source.delay(str(source.id))
    meta = {**(source.meta_json or {})}
    meta["ocr_status"] = "queued"
    meta["ocr_task_id"] = task.id
    source.meta_json = meta
    db.commit()
    return task.id



def _process_source(db: Session, source: SourceDocument):
    try:
        data, payload_meta = _load_source_bytes(source)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    parse_name = (
        payload_meta.get("object_name")
        or payload_meta.get("local_path")
        or (source.meta_json or {}).get("file_name")
        or source.file_uri
    )
    parsed = parse_document_bytes(data, filename=str(parse_name or ""), allow_ocr=False)
    pages = parsed.get("pages", [])
    parse_meta = parsed.get("meta") or {}
    extraction_mode = parse_meta.get("text_extraction")

    current_meta = source.meta_json or {}
    already_ocr_done = str(current_meta.get("ocr_status") or "").lower() == "done"
    if str(current_meta.get("text_extraction") or "").lower() in {"pdf_ocr", "pdf_text_plus_ocr"}:
        already_ocr_done = True
    ocr_recommended = bool(parse_meta.get("ocr_recommended")) and not already_ocr_done
    result = _persist_parsed_source(
        db,
        source,
        pages,
        payload_meta,
        extraction_mode=extraction_mode,
        fallback_extraction="metadata_fallback_pending_ocr" if ocr_recommended else "metadata_fallback_no_ocr",
        extra_meta={
            "ocr_recommended": True if ocr_recommended else None,
            "ocr_status": "pending" if ocr_recommended else "not_needed",
            "ocr_task_id": None,
            "ocr_applied": None,
        },
    )

    if ocr_recommended:
        result["ocr_queued"] = True
        result["ocr_task_id"] = _queue_ocr_task(db, source)
    else:
        result["ocr_queued"] = False
    return result



def _process_source_ocr(db: Session, source: SourceDocument):
    try:
        data, payload_meta = _load_source_bytes(source)
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}

    source.meta_json = {**(source.meta_json or {}), "ocr_status": "running"}
    db.commit()

    parse_name = (
        payload_meta.get("object_name")
        or payload_meta.get("local_path")
        or (source.meta_json or {}).get("file_name")
        or source.file_uri
    )
    parsed = parse_document_bytes(
        data,
        filename=str(parse_name or ""),
        allow_ocr=True,
        force_ocr=True,
    )
    pages = parsed.get("pages", [])
    parse_meta = parsed.get("meta") or {}
    extraction_mode = parse_meta.get("text_extraction")
    ocr_applied = bool(parse_meta.get("ocr_applied"))
    result = _persist_parsed_source(
        db,
        source,
        pages,
        payload_meta,
        extraction_mode=extraction_mode,
        fallback_extraction="metadata_fallback_after_ocr",
        extra_meta={
            "ocr_recommended": None,
            "ocr_status": "done" if ocr_applied else "attempted_no_text",
            "ocr_task_id": None,
            "ocr_attempted": True,
            "ocr_applied": True if ocr_applied else None,
        },
    )
    result["ocr_applied"] = ocr_applied
    return result

def _resolve_case_no(jurisdiction_case: JurisdictionCase) -> str | None:
    if (jurisdiction_case.jurisdiction or "").upper() == "EU":
        return jurisdiction_case.application_no or jurisdiction_case.publication_no
    return jurisdiction_case.publication_no or jurisdiction_case.application_no


def _to_bytes_io(payload: bytes) -> BytesIO:
    return BytesIO(payload)


def _build_epo_zip_like_path(jurisdiction_case: JurisdictionCase, filename: str) -> Path | None:
    if (jurisdiction_case.jurisdiction or "").upper() != "EU":
        return None
    case_no = _resolve_case_no(jurisdiction_case)
    if not case_no:
        return None
    try:
        from ep_ingest.identifiers import normalize_identifier
        from ep_ingest.storage import build_output_paths
    except Exception:
        return None
    try:
        normalized = normalize_identifier(case_no)
        out_root = Path(settings.ep_ingest_out_dir or "/data")
        paths = build_output_paths(out_root, normalized.patent_id, jurisdiction="EP")
        return paths.files_dir / "zip_archive" / filename
    except Exception:
        return None


def _should_store_epo_under_zip_archive(
    fetched: dict[str, Any],
    doc_meta: dict[str, Any],
) -> bool:
    existing = str(fetched.get("local_path") or doc_meta.get("local_path") or "").strip()
    if existing:
        normalized = existing.replace("\\", "/").lower()
        return "/zip_archive/" in normalized or normalized.endswith("/zip_archive")

    if doc_meta.get("image_path"):
        return False

    source_uri = str(fetched.get("source_uri") or doc_meta.get("source_uri") or "").strip().lower()
    if "/published-data/images/" in source_uri:
        return False

    return bool(doc_meta.get("register_document_id"))


def _resolve_local_output_path(
    jurisdiction_case: JurisdictionCase,
    provider_name: str,
    filename: str,
    fetched: dict[str, Any],
    doc_meta: dict[str, Any],
) -> Path:
    existing = str(fetched.get("local_path") or doc_meta.get("local_path") or "").strip()
    if existing:
        return Path(existing)

    if provider_name == "epo" and _should_store_epo_under_zip_archive(fetched, doc_meta):
        epo_path = _build_epo_zip_like_path(jurisdiction_case, filename)
        if epo_path is not None:
            return epo_path

    root = Path(settings.ep_ingest_out_dir or "/data")
    return root / "sources" / str(jurisdiction_case.id) / filename


def _persist_local_copy(local_path: Path, data: bytes) -> str | None:
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
    except Exception:
        return None
    return str(local_path)


def _resolve_files_dir(source_path: Path) -> Path:
    for parent in source_path.parents:
        if parent.name.lower() == "files":
            return parent
    return source_path.parent


def _unique_target_path(target_dir: Path, file_name: str) -> Path:
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


def _candidate_data_roots() -> list[Path]:
    roots: list[Path] = []
    configured = Path(settings.ep_ingest_out_dir or "/data")
    roots.append(configured)
    roots.append(Path("data"))
    roots.append(Path.cwd() / "data")

    dedup: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(root)
    return dedup


def _resolve_source_path(local_path: str, file_name: str) -> Path | None:
    candidates: list[Path] = []
    raw = local_path.strip()
    if raw:
        candidates.append(Path(raw))

    normalized = raw.replace("\\", "/")
    rel_after_data = ""
    marker = "/data/"
    idx = normalized.lower().find(marker)
    if idx >= 0:
        rel_after_data = normalized[idx + len(marker) :]
    elif normalized.lower().startswith("/data"):
        rel_after_data = normalized[6:].lstrip("/")

    roots = _candidate_data_roots()
    if rel_after_data:
        rel_path = Path(*[part for part in rel_after_data.split("/") if part])
        for root in roots:
            candidates.append(root / rel_path)

    for path in candidates:
        try:
            if path.exists() and path.is_file():
                return path
        except Exception:
            continue

    if file_name:
        for root in roots:
            if not root.exists():
                continue
            matches = [p for p in root.rglob(file_name) if p.is_file()]
            if matches:
                return max(matches, key=lambda p: p.stat().st_mtime)
    return None


def _match_comparison_category(*, document_type_raw: str, file_name: str) -> str | None:
    text = f"{document_type_raw} {file_name}".lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if "reply to communication from the examining division" in text:
        return "reply_to_communication_from_examining_division"
    if "amended claims with annotations" in text:
        return "amended_claims_with_annotations"

    for category, keywords in _COMPARISON_CATEGORY_RULES:
        if category == "claims":
            if not re.search(r"\bclaims\b", text):
                continue
        elif not any(keyword in text for keyword in keywords):
            continue

        if "claims" in category and any(hint in text for hint in _CLAIMS_TRANSLATION_HINTS):
            continue
        return category
    return None


def _export_comparison_candidates(records: list[dict[str, str]]) -> dict[str, Any]:
    comparison_dirs: set[Path] = set()
    selected: list[dict[str, str]] = []
    seen_sources: set[Path] = set()

    for record in records:
        local_path = str(record.get("local_path") or "").strip()
        file_name = str(record.get("file_name") or "").strip()
        source_path = _resolve_source_path(local_path, file_name)
        if source_path is None:
            continue
        if source_path in seen_sources:
            continue
        if not source_path.exists() or not source_path.is_file():
            continue

        category = _match_comparison_category(
            document_type_raw=str(record.get("document_type_raw") or ""),
            file_name=file_name or source_path.name,
        )
        if not category:
            continue

        files_dir = _resolve_files_dir(source_path)
        comparison_dir = files_dir / "comparison_candidates"
        if comparison_dir not in comparison_dirs:
            _reset_comparison_dir(comparison_dir)
            comparison_dirs.add(comparison_dir)
        target_dir = comparison_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = _unique_target_path(target_dir, source_path.name)

        try:
            shutil.copy2(source_path, target_path)
        except Exception:
            continue

        seen_sources.add(source_path)
        selected.append(
            {
                "category": category,
                "source_path": str(source_path),
                "target_path": str(target_path),
                "document_type_raw": str(record.get("document_type_raw") or ""),
                "file_name": str(record.get("file_name") or source_path.name),
            }
        )

    if not selected:
        return {"selected_count": 0, "categories": []}

    manifest_dir = _resolve_files_dir(Path(selected[0]["source_path"])) / "comparison_candidates"
    manifest_path = manifest_dir / "manifest.json"
    payload = {
        "selected_count": len(selected),
        "categories": sorted({item["category"] for item in selected}),
        "files": selected,
    }
    try:
        manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload


def _reset_comparison_dir(comparison_dir: Path) -> None:
    if comparison_dir.exists():
        shutil.rmtree(comparison_dir)
    comparison_dir.mkdir(parents=True, exist_ok=True)


def _create_source_from_fetched(
    db: Session,
    jurisdiction_case: JurisdictionCase,
    provider_name: str,
    doc_meta: dict[str, Any],
    fetched: dict[str, Any],
) -> SourceDocument | None:
    data = fetched.get("bytes")
    if not data:
        return None

    filename = fetched.get("file_name") or doc_meta.get("file_name") or f"{provider_name}_{uuid.uuid4()}.bin"
    safe_name = filename.replace("/", "_").replace("\\", "_")
    object_name = f"{jurisdiction_case.id}/{uuid.uuid4()}_{safe_name}"
    content_type = fetched.get("content_type") or doc_meta.get("content_type") or "application/octet-stream"

    storage_client.put_object(object_name, _to_bytes_io(data), content_type)
    local_output_path = _resolve_local_output_path(
        jurisdiction_case,
        provider_name,
        safe_name,
        fetched,
        doc_meta,
    )
    local_path = _persist_local_copy(local_output_path, data)
    normalized_doc_type = classify_doc_type(
        raw_label=str(doc_meta.get("document_type_raw") or doc_meta.get("doc_type") or ""),
        file_name=filename,
        fallback=doc_meta.get("doc_type") or infer_doc_type(filename),
    )
    source = SourceDocument(
        jurisdiction_case_id=jurisdiction_case.id,
        doc_type=normalized_doc_type,
        language=doc_meta.get("language"),
        source_type=provider_name,
        file_uri=storage_client.object_uri(object_name),
        meta_json={
            "provider": provider_name,
            "source_uri": fetched.get("source_uri") or doc_meta.get("source_uri"),
            "file_name": filename,
            "local_path": local_path or fetched.get("local_path") or doc_meta.get("local_path"),
        },
        version=doc_meta.get("version"),
        included=should_auto_include(normalized_doc_type),
    )
    db.add(source)
    db.flush()
    return source


def _progress_percent(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, int(current * 100 / total)))


def _emit_task_progress(task, **payload: Any) -> None:
    if task is None:
        return
    task.update_state(state="PROGRESS", meta=payload)


def _ingest_jurisdiction_case(
    db: Session,
    jurisdiction_case: JurisdictionCase,
    ingest_options: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    case_no = _resolve_case_no(jurisdiction_case)
    if not case_no:
        return {
            "status": "missing",
            "created_source_ids": [],
            "missing_reason": f"Missing publication_no/application_no for {jurisdiction_case.jurisdiction}",
            "followup_suggestions": [
                "Provide publication number or application number, then rerun ingest.",
                "Use /sources/upload to add office actions and responses manually.",
            ],
        }

    provider_order = resolve_provider_order(
        jurisdiction=jurisdiction_case.jurisdiction,
        providers=ingest_options.get("providers"),
        prefer_official=bool(ingest_options.get("prefer_official", True)),
        include_dms_fallback=bool(ingest_options.get("include_dms_fallback", True)),
    )
    if not provider_order:
        return {
            "status": "missing",
            "created_source_ids": [],
            "missing_reason": "No valid providers available for ingest",
            "followup_suggestions": [
                "Use providers from [cnipr, epo, uspto, dms].",
                "Use /sources/upload to add documents manually.",
            ],
        }

    attempted: list[str] = []
    created_source_ids: list[str] = []
    provider_hits = 0

    for provider_name in provider_order:
        adapter = ADAPTERS[provider_name]
        attempted.append(provider_name)
        if progress_callback:
            progress_callback(
                {
                    "stage": "listing_documents",
                    "status": "running",
                    "message": f"{jurisdiction_case.jurisdiction}: 正在列出 {provider_name} 文档。",
                    "provider": provider_name,
                    "documents_discovered": 0,
                    "documents_fetched": len(created_source_ids),
                }
            )
        docs = adapter.list_documents(case_no)
        if not docs:
            continue

        provider_hits += 1
        if progress_callback:
            progress_callback(
                {
                    "stage": "downloading_documents",
                    "status": "running",
                    "message": f"{jurisdiction_case.jurisdiction}: 正在下载 {provider_name} 文档。",
                    "provider": provider_name,
                    "documents_discovered": len(docs),
                    "documents_fetched": len(created_source_ids),
                }
            )
        comparison_candidates: list[dict[str, str]] = []
        for idx, doc_meta in enumerate(docs, start=1):
            fetched = adapter.fetch_document(doc_meta)
            source = _create_source_from_fetched(db, jurisdiction_case, provider_name, doc_meta, fetched)
            if not source:
                if progress_callback:
                    progress_callback(
                        {
                            "stage": "downloading_documents",
                            "status": "running",
                            "message": f"{jurisdiction_case.jurisdiction}: 已处理 {idx}/{len(docs)} 个文档。",
                            "provider": provider_name,
                            "documents_discovered": len(docs),
                            "documents_fetched": len(created_source_ids),
                        }
                    )
                continue
            created_source_ids.append(str(source.id))
            if provider_name == "epo":
                meta = source.meta_json or {}
                comparison_candidates.append(
                    {
                        "local_path": str(
                            meta.get("local_path")
                            or fetched.get("local_path")
                            or doc_meta.get("local_path")
                            or ""
                        ),
                        "file_name": str(doc_meta.get("file_name") or meta.get("file_name") or ""),
                        "document_type_raw": str(doc_meta.get("document_type_raw") or ""),
                    }
                )
            if ingest_options.get("trigger_processing", True):
                process_source.delay(str(source.id))
            if progress_callback:
                progress_callback(
                    {
                        "stage": "downloading_documents",
                        "status": "running",
                        "message": f"{jurisdiction_case.jurisdiction}: 已下载 {idx}/{len(docs)} 个文档。",
                        "provider": provider_name,
                        "documents_discovered": len(docs),
                        "documents_fetched": len(created_source_ids),
                    }
                )

        if provider_name == "epo" and comparison_candidates:
            _export_comparison_candidates(comparison_candidates)

        # Once official sources are found, skip fallback providers to reduce duplicates.
        if provider_name != "dms":
            break

    db.commit()

    if created_source_ids:
        return {
            "status": "ok",
            "attempted_providers": attempted,
            "provider_hits": provider_hits,
            "created_source_ids": created_source_ids,
            "missing_reason": None,
            "followup_suggestions": [],
        }

    return {
        "status": "missing",
        "attempted_providers": attempted,
        "provider_hits": provider_hits,
        "created_source_ids": [],
        "missing_reason": "No documents fetched from providers",
        "followup_suggestions": [
            "Check provider connectivity and credentials.",
            "Use /sources/upload to add Office Action / Response / Amendment files.",
        ],
    }


@celery_app.task(name="app.tasks.ingest.process_source")
def process_source(source_id: str):
    db = SessionLocal()
    try:
        sid = uuid.UUID(source_id)
        source = db.query(SourceDocument).filter(SourceDocument.id == sid).first()
        if not source:
            return {"status": "error", "reason": "source not found"}
        return _process_source(db, source)
    finally:
        db.close()


@celery_app.task(name="app.tasks.ingest.ocr_source")
def ocr_source(source_id: str):
    db = SessionLocal()
    try:
        sid = uuid.UUID(source_id)
        source = db.query(SourceDocument).filter(SourceDocument.id == sid).first()
        if not source:
            return {"status": "error", "reason": "source not found"}
        try:
            return _process_source_ocr(db, source)
        except Exception as exc:
            source.meta_json = {
                **(source.meta_json or {}),
                "ocr_status": "error",
                "ocr_task_id": None,
                "ocr_error": str(exc),
            }
            db.commit()
            return {"status": "error", "reason": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.ingest.ingest_case", bind=True)
def ingest_case(self, case_id: str, options: dict[str, Any] | None = None):
    ingest_options = {**DEFAULT_INGEST_OPTIONS, **(options or {})}
    db = SessionLocal()
    try:
        _emit_task_progress(
            self,
            case_id=case_id,
            stage="initializing",
            status="running",
            message="正在初始化采集任务。",
            current=0,
            total=1,
            percent=0,
            created_sources=0,
        )
        cid = uuid.UUID(case_id)
        case = db.query(PatentCase).filter(PatentCase.id == cid).first()
        if not case:
            return {"status": "error", "case_id": case_id, "reason": "case not found"}

        jurisdiction_cases = db.query(JurisdictionCase).filter(JurisdictionCase.case_id == case.id).all()
        if not jurisdiction_cases:
            return {
                "status": "missing",
                "case_id": case_id,
                "missing_reason": "No jurisdiction cases found",
                "followup_suggestions": [
                    "Add at least one jurisdiction case (CN/EU/US).",
                    "Or upload documents directly via /sources/upload.",
                ],
            }

        storage_client.ensure_bucket()
        total_jurisdictions = len(jurisdiction_cases)
        total_documents = 0
        completed_documents = 0
        created_sources_count = 0
        case_results = []

        for index, jc in enumerate(jurisdiction_cases, start=1):
            jurisdiction_label = f"{jc.jurisdiction or 'UNKNOWN'} {(_resolve_case_no(jc) or '').strip()}".strip()
            _emit_task_progress(
                self,
                case_id=case_id,
                stage="preparing_jurisdiction",
                status="running",
                message=f"正在处理 {jurisdiction_label}",
                current=completed_documents,
                total=max(total_documents, completed_documents, 1),
                percent=_progress_percent(completed_documents, max(total_documents, completed_documents, 1)),
                created_sources=created_sources_count,
                jurisdiction_index=index,
                jurisdiction_total=total_jurisdictions,
            )

            def progress_callback(payload: dict[str, Any]) -> None:
                nonlocal total_documents, completed_documents, created_sources_count
                discovered = payload.get("documents_discovered")
                fetched = payload.get("documents_fetched")
                if isinstance(discovered, int) and discovered >= 0:
                    total_documents = max(total_documents, completed_documents + discovered)
                if isinstance(fetched, int) and fetched >= 0:
                    completed_documents = fetched
                    created_sources_count = fetched
                current_total = max(total_documents, completed_documents, 1)
                _emit_task_progress(
                    self,
                    case_id=case_id,
                    stage=str(payload.get("stage") or "running"),
                    status=str(payload.get("status") or "running"),
                    message=str(payload.get("message") or f"正在处理 {jurisdiction_label}"),
                    current=completed_documents,
                    total=current_total,
                    percent=_progress_percent(completed_documents, current_total),
                    created_sources=created_sources_count,
                    jurisdiction_index=index,
                    jurisdiction_total=total_jurisdictions,
                    provider=payload.get("provider"),
                )

            case_results.append(
                _ingest_jurisdiction_case(
                    db,
                    jc,
                    ingest_options,
                    progress_callback=progress_callback,
                )
            )
        created_source_ids = [sid for item in case_results for sid in item.get("created_source_ids", [])]
        missing_items = [item for item in case_results if item.get("status") != "ok"]
        suggestions = []
        for item in missing_items:
            suggestions.extend(item.get("followup_suggestions", []))

        dedup_suggestions = []
        for suggestion in suggestions:
            if suggestion not in dedup_suggestions:
                dedup_suggestions.append(suggestion)

        return {
            "status": "ok" if created_source_ids else "missing",
            "case_id": case_id,
            "created_sources": len(created_source_ids),
            "created_source_ids": created_source_ids,
            "jurisdiction_results": case_results,
            "missing": not bool(created_source_ids),
            "missing_reason": None if created_source_ids else "No sources fetched for the case",
            "followup_suggestions": dedup_suggestions,
        }
    finally:
        db.close()














