from __future__ import annotations

import json
import logging
import re
import shutil
import mimetypes
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.pipelines.adapters.base import IngestAdapter
from app.services.document_classifier import classify_doc_type, infer_doc_type

OPS_BASE_URL = "https://ops.epo.org/3.2"
OPS_REST_BASE_URL = f"{OPS_BASE_URL}/rest-services"
OPS_AUTH_URL = f"{OPS_BASE_URL}/auth/accesstoken"

_PUB_REF_RE = re.compile(r"^EP(\d+)([A-Z]\d?)?$", re.IGNORECASE)
_PUB_KIND_ALLOWED = set("ABCUTWY")
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
LOGGER = logging.getLogger(__name__)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _extract_image_path(href: str) -> str | None:
    text = _norm(href)
    if not text:
        return None
    marker = "/published-data/images/"
    lowered = text.lower()
    idx = lowered.find(marker)
    if idx >= 0:
        return text[idx + len(marker) :].lstrip("/")
    parsed = urlparse(text)
    if parsed.path.lower().find(marker) >= 0:
        idx = parsed.path.lower().find(marker)
        return parsed.path[idx + len(marker) :].lstrip("/")
    if text.startswith(("EP/", "WO/", "US/")):
        return text
    return None


class _OpsClient:
    def __init__(self, *, key: str, secret: str, timeout_seconds: int) -> None:
        self.key = key
        self.secret = secret
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "patent-notebook/1.0 (+OPS-v3.2)"},
        )
        self._token: str | None = None
        self._token_expires_at = 0.0

    def _ensure_token(self) -> str | None:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        try:
            response = self.client.post(
                OPS_AUTH_URL,
                auth=(self.key, self.secret),
                content="grant_type=client_credentials",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except httpx.RequestError:
            return None
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        token = payload.get("access_token")
        if not token:
            return None
        expires_in = int(payload.get("expires_in", 1200))
        self._token = str(token)
        self._token_expires_at = time.monotonic() + max(30, expires_in - 30)
        return self._token

    def _request(
        self,
        *,
        method: str,
        path: str,
        accept: str,
        params: dict | None = None,
        content: str | bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response | None:
        token = self._ensure_token()
        if not token:
            return None
        headers = {"Authorization": f"Bearer {token}", "Accept": accept}
        if content_type:
            headers["Content-Type"] = content_type
        url = f"{OPS_REST_BASE_URL}/{path.lstrip('/')}"
        try:
            response = self.client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                content=content,
            )
        except httpx.RequestError:
            return None
        if response.status_code == 401:
            self._token = None
            return None
        if response.status_code >= 400:
            return None
        return response

    def register_biblio(self, reference_type: str, epodoc_input: str) -> str | None:
        response = self._request(
            method="GET",
            path=f"register/{reference_type}/epodoc/{epodoc_input}/biblio",
            accept="application/register+xml",
        )
        if not response:
            return None
        return response.text

    def images_inquiry(self, publication_epodoc: str) -> str | None:
        response = self._request(
            method="GET",
            path=f"published-data/images/publication/epodoc/{publication_epodoc}",
            accept="application/xml",
        )
        if response:
            return response.text
        # Some OPS resources reject application/xml for this endpoint.
        retry_response = self._request(
            method="GET",
            path=f"published-data/images/publication/epodoc/{publication_epodoc}",
            accept="text/xml",
        )
        if not retry_response:
            return None
        return retry_response.text

    def image_retrieval(self, image_path: str, page: int = 1) -> bytes | None:
        response = self._request(
            method="POST",
            path="published-data/images",
            accept="application/pdf",
            params={"Range": str(page)},
            content=image_path,
            content_type="text/plain",
        )
        if not response:
            return None
        return response.content


class EPOAdapter(IngestAdapter):
    name = "epo"
    is_official = True

    def __init__(self):
        self._ops: _OpsClient | None = None
        if settings.epo_ops_key and settings.epo_ops_secret:
            self._ops = _OpsClient(
                key=settings.epo_ops_key,
                secret=settings.epo_ops_secret,
                timeout_seconds=settings.epo_ops_timeout_sec,
            )

    def list_documents(self, case_no: str) -> List[Dict]:
        if not case_no:
            return []

        # Prefer EP Register doclist + ZIP archive for complete prosecution files.
        register_docs = self._list_documents_from_register(case_no)
        if register_docs:
            return register_docs

        # Strict mode: if enabled, do not fallback to OPS image endpoints.
        if settings.ep_register_only:
            return []

        if not self._ops:
            return []

        documents: List[Dict] = []
        seen: set[str] = set()
        for publication_ref in self._collect_publication_refs(case_no):
            image_paths = self._image_paths_from_inquiry(publication_ref)
            if not image_paths:
                image_paths = self._heuristic_image_paths(publication_ref)
            for image_path in image_paths:
                key = image_path.lower()
                if key in seen:
                    continue
                seen.add(key)
                parts = [part for part in image_path.split("/") if part]
                file_name = f"{parts[-1]}.pdf"
                if len(parts) >= 4:
                    file_name = f"{parts[-4]}{parts[-3]}{parts[-2]}_{parts[-1]}.pdf"
                documents.append(
                    {
                        "doc_type": "other",
                        "language": "en",
                        "file_name": file_name,
                        "document_type_raw": parts[-1] if parts else "ops_image",
                        "content_type": "application/pdf",
                        "image_path": image_path,
                        "source_uri": f"{OPS_REST_BASE_URL}/published-data/images/{image_path}",
                    }
                )
        return documents

    def fetch_document(self, doc_meta: dict) -> Dict:
        # Register Zip Archive path: files are already downloaded to local disk by ep_ingest.
        local_path = _norm(str(doc_meta.get("local_path") or ""))
        if local_path:
            path = Path(local_path)
            if path.exists() and path.is_file():
                payload = path.read_bytes()
                if payload:
                    content_type = doc_meta.get("content_type") or self._content_type_for_path(path)
                    return {
                        "file_name": doc_meta.get("file_name") or path.name,
                        "content_type": content_type,
                        "bytes": payload,
                        "source_uri": doc_meta.get("source_uri") or str(path),
                        "local_path": str(path),
                    }

        # OPS fallback path.
        if not self._ops:
            return {}
        image_path = _norm(doc_meta.get("image_path"))
        if not image_path:
            return {}
        payload = self._ops.image_retrieval(image_path=image_path, page=1)
        if not payload:
            return {}
        if not payload.startswith(b"%PDF"):
            return {}
        return {
            "file_name": doc_meta.get("file_name") or f"{image_path.rsplit('/', 1)[-1]}.pdf",
            "content_type": "application/pdf",
            "bytes": payload,
            "source_uri": f"{OPS_REST_BASE_URL}/published-data/images/{image_path}",
        }

    def _list_documents_from_register(self, case_no: str) -> List[Dict]:
        try:
            from ep_ingest.service import EpIngestionService
            from ep_ingest.identifiers import normalize_identifier
            from ep_ingest.storage import build_output_paths
        except Exception:
            return []

        out_root = Path(settings.ep_ingest_out_dir or "/data")
        dataset = None
        last_error: Exception | None = None
        for attempt in range(5):
            if attempt > 0:
                # Clear case cache and retry once to mitigate transient anti-bot/challenge pages.
                try:
                    normalized = normalize_identifier(case_no)
                    paths = build_output_paths(out_root, normalized.patent_id, jurisdiction="EP")
                    if paths.cache_dir.exists():
                        shutil.rmtree(paths.cache_dir, ignore_errors=True)
                        paths.cache_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                time.sleep(1.0)
            try:
                service = EpIngestionService(
                    delay_seconds=settings.ep_register_delay_sec,
                    concurrency=max(1, settings.ep_register_concurrency),
                    log_level=settings.ep_register_log_level,
                    browser_fallback=bool(settings.ep_register_browser_fallback),
                    browser_headless=bool(settings.ep_register_browser_headless),
                    browser_user_data_dir=(settings.ep_register_browser_user_data_dir or None),
                    proxy=(settings.ep_register_proxy or None),
                )
                dataset = service.fetch(case_no, out_dir=out_root)
                if dataset.documents:
                    break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                dataset = None
                continue
        if dataset is None:
            if last_error is not None:
                LOGGER.warning("EP Register fetch failed for %s: %s", case_no, last_error)
            return []
        if not dataset.documents:
            LOGGER.warning("EP Register returned no documents for %s", case_no)

        try:
            normalized = normalize_identifier(case_no)
            paths = build_output_paths(out_root, normalized.patent_id, jurisdiction="EP")
        except Exception:
            paths = None

        files_dir = getattr(paths, "files_dir", None) if paths else None
        zip_documents = self._list_documents_from_zip_archive(
            zip_dir=(files_dir / "zip_archive") if files_dir else None,
            dataset=dataset,
        )
        if zip_documents:
            return zip_documents

        documents: List[Dict] = []
        for idx, item in enumerate(dataset.documents):
            local_path = _norm(item.local_path)
            if not local_path:
                continue
            path = Path(local_path)
            if not path.exists() or not path.is_file():
                continue

            doc_type = self._map_register_doc_type(item.document_type_raw, path.name)
            source_uri = _norm(item.file_url) or str(path)
            documents.append(
                {
                    "doc_type": doc_type,
                    "language": "en",
                    "file_name": path.name,
                    "document_type_raw": item.document_type_raw,
                    "content_type": self._content_type_for_path(path),
                    "local_path": str(path),
                    "source_uri": source_uri,
                    "register_document_id": item.register_document_id,
                    "register_case_id": dataset.register_case_id,
                    "sequence": idx,
                }
            )
        return documents

    def _list_documents_from_zip_archive(self, *, zip_dir: Path | None, dataset) -> List[Dict]:
        if zip_dir is None or not zip_dir.exists() or not zip_dir.is_dir():
            return []

        metadata_by_path: dict[str, Dict] = {}
        metadata_by_name: dict[str, Dict] = {}
        for idx, item in enumerate(getattr(dataset, "documents", []) or []):
            local_path = _norm(getattr(item, "local_path", ""))
            file_name = Path(local_path).name if local_path else ""
            record = {
                "document_type_raw": getattr(item, "document_type_raw", "") or "",
                "source_uri": _norm(getattr(item, "file_url", "")) or local_path,
                "register_document_id": getattr(item, "register_document_id", "") or file_name,
                "sequence": idx,
            }
            if local_path:
                metadata_by_path[local_path] = record
            if file_name and file_name not in metadata_by_name:
                metadata_by_name[file_name] = record

        documents: List[Dict] = []
        for idx, path in enumerate(sorted((p for p in zip_dir.rglob("*") if p.is_file()), key=lambda p: p.name.lower())):
            key = str(path)
            meta = metadata_by_path.get(key) or metadata_by_name.get(path.name) or {}
            document_type_raw = str(meta.get("document_type_raw") or path.stem)
            documents.append(
                {
                    "doc_type": self._map_register_doc_type(document_type_raw, path.name),
                    "language": "en",
                    "file_name": path.name,
                    "document_type_raw": document_type_raw,
                    "content_type": self._content_type_for_path(path),
                    "local_path": str(path),
                    "source_uri": str(meta.get("source_uri") or path),
                    "register_document_id": str(meta.get("register_document_id") or path.stem),
                    "register_case_id": getattr(dataset, "register_case_id", ""),
                    "sequence": int(meta.get("sequence", idx)),
                }
            )
        return documents

    def _export_comparison_candidates(self, documents: List[Dict]) -> None:
        comparison_dirs: set[Path] = set()
        selected: list[dict] = []
        seen_sources: set[Path] = set()

        for doc in documents:
            local_path = _norm(str(doc.get("local_path") or ""))
            if not local_path:
                continue
            source_path = Path(local_path)
            if source_path in seen_sources:
                continue
            if not source_path.exists() or not source_path.is_file():
                continue

            category = self._match_comparison_category(
                document_type_raw=str(doc.get("document_type_raw") or ""),
                file_name=str(doc.get("file_name") or source_path.name),
            )
            if not category:
                continue

            files_dir = self._resolve_files_dir(source_path)
            comparison_dir = files_dir / "comparison_candidates"
            if comparison_dir not in comparison_dirs:
                self._reset_comparison_dir(comparison_dir)
                comparison_dirs.add(comparison_dir)
            target_dir = comparison_dir / category
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = self._unique_target_path(target_dir, source_path.name)

            try:
                shutil.copy2(source_path, target_path)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to copy comparison candidate %s: %s", source_path, exc)
                continue

            seen_sources.add(source_path)
            selected.append(
                {
                    "category": category,
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "document_type_raw": str(doc.get("document_type_raw") or ""),
                    "file_name": str(doc.get("file_name") or source_path.name),
                }
            )

        if not selected:
            return

        manifest_dir = self._resolve_files_dir(Path(selected[0]["source_path"])) / "comparison_candidates"
        manifest_path = manifest_dir / "manifest.json"
        payload = {
            "selected_count": len(selected),
            "categories": sorted({item["category"] for item in selected}),
            "files": selected,
        }
        try:
            manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            LOGGER.info("Exported %d comparison candidates to %s", len(selected), manifest_dir)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to write comparison candidate manifest: %s", exc)

    @staticmethod
    def _resolve_files_dir(source_path: Path) -> Path:
        for parent in source_path.parents:
            if parent.name.lower() == "files":
                return parent
        return source_path.parent

    @staticmethod
    def _reset_comparison_dir(comparison_dir: Path) -> None:
        if comparison_dir.exists():
            shutil.rmtree(comparison_dir)
        comparison_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
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
    @staticmethod
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

    @staticmethod
    def _content_type_for_path(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return "application/pdf"
        if suffix in {".html", ".htm"}:
            return "text/html"
        if suffix == ".xml":
            return "application/xml"
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"

    @staticmethod
    def _map_register_doc_type(raw_label: str | None, file_name: str) -> str:
        return classify_doc_type(raw_label=raw_label, file_name=file_name, fallback=infer_doc_type(file_name, fallback="other"))

    def _collect_publication_refs(self, case_no: str) -> List[str]:
        normalized = re.sub(r"\s+", "", case_no).upper()
        candidates: List[str] = []
        biblio_xml = self._fetch_biblio_xml(normalized)
        if biblio_xml:
            candidates.extend(self.extract_publication_refs_from_biblio_xml(biblio_xml))
        match = _PUB_REF_RE.match(normalized)
        if match:
            digits = match.group(1)
            kind = match.group(2)
            if kind:
                candidates.append(f"EP{digits}{kind}")
            else:
                candidates.append(f"EP{digits}A1")
                candidates.append(f"EP{digits}")
        return _dedupe(candidates)

    def _fetch_biblio_xml(self, normalized_case_no: str) -> str | None:
        if not self._ops:
            return None
        epodoc_inputs = self._build_epodoc_candidates(normalized_case_no)
        ref_types = self._reference_types(normalized_case_no)
        for ref_type in ref_types:
            for epodoc_input in epodoc_inputs:
                xml_text = self._ops.register_biblio(ref_type, epodoc_input)
                if xml_text:
                    return xml_text
        return None

    @staticmethod
    def _build_epodoc_candidates(normalized_case_no: str) -> List[str]:
        raw = normalized_case_no
        if raw.startswith("EP"):
            raw = raw[2:]
        no_dot = raw.replace(".", "")
        candidates = [f"EP{no_dot}"]
        if "." in raw:
            candidates.append(f"EP{raw.split('.', 1)[0]}")
        return _dedupe(candidates)

    @staticmethod
    def _reference_types(normalized_case_no: str) -> List[str]:
        if "." in normalized_case_no:
            return ["application", "publication"]
        return ["publication", "application"]

    @staticmethod
    def extract_publication_refs_from_biblio_xml(xml_text: str) -> List[str]:
        refs: List[str] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        for node in root.iter():
            if _local_name(node.tag) != "document-id":
                continue
            country = ""
            doc_number = ""
            kind = ""
            for child in node:
                name = _local_name(child.tag)
                value = _norm(child.text).upper()
                if name == "country":
                    country = value
                elif name == "doc-number":
                    doc_number = value
                elif name == "kind":
                    kind = value
            if country == "EP" and doc_number and kind and kind[0] in _PUB_KIND_ALLOWED:
                refs.append(f"EP{doc_number}{kind}")

        return _dedupe(refs)

    def _image_paths_from_inquiry(self, publication_ref: str) -> List[str]:
        if not self._ops:
            return []
        xml_text = self._ops.images_inquiry(publication_ref)
        if not xml_text:
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        paths: List[str] = []
        for node in root.iter():
            if _local_name(node.tag) != "document-instance":
                continue
            href = ""
            for child in node.iter():
                for attr_name, attr_value in child.attrib.items():
                    if attr_name.lower().endswith("href"):
                        href = _norm(attr_value)
                        if href:
                            break
                if href:
                    break
            image_path = _extract_image_path(href)
            if not image_path:
                continue
            lowered = image_path.lower()
            if "fullimage" in lowered or "firstpage" in lowered:
                paths.append(image_path)

        return _dedupe(paths)

    @staticmethod
    def _heuristic_image_paths(publication_ref: str) -> List[str]:
        ref = publication_ref.upper()
        match = _PUB_REF_RE.match(ref)
        if not match:
            return []
        digits = match.group(1)
        kind = match.group(2) or "A1"
        return [
            f"EP/{digits}/{kind}/fullimage",
            f"EP/{digits}/{kind}/firstpage",
        ]







