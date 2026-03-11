from __future__ import annotations

import hashlib
import io
import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from ep_ingest.errors import BlockedError, NotFoundError, ParsingError, UnexpectedHtmlError
from ep_ingest.http_client import HttpFetcher
from ep_ingest.metrics import Metrics
from ep_ingest.models import DocumentRecord, IdentifierMapping, NormalizedIdentifier

try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except Exception:
    HTML_PARSER = "html.parser"


@dataclass
class AcquisitionResult:
    register_case_id: str
    identifiers: IdentifierMapping
    documents: list[DocumentRecord]


@dataclass
class ZipArchivePayload:
    action_url: str
    application_number: str
    document_ids: list[str]
    form_data: dict[str, str]
    referer_url: str


class RegisterScraper:
    BASE = "https://register.epo.org"

    def __init__(
        self,
        *,
        fetcher: HttpFetcher,
        metrics: Metrics,
        logger,
        concurrency: int = 2,
    ) -> None:
        self.fetcher = fetcher
        self.metrics = metrics
        self.logger = logger
        self.concurrency = max(1, concurrency)

    def acquire(self, identifier: NormalizedIdentifier, files_dir: Path) -> AcquisitionResult:
        case_url, case_html = self._resolve_case_page(identifier)
        all_docs_url, all_docs_html = self._resolve_all_documents_page(case_url, case_html)
        try:
            documents = self._parse_documents_table(all_docs_html, all_docs_url)
        except Exception as exc:  # noqa: BLE001
            self.metrics.inc("parse_fail")
            self.logger.warning("Failed to parse Register documents table, fallback to ZIP-only mode: %s", exc)
            documents = []

        if documents:
            self._download_documents(
                documents,
                files_dir,
                all_docs_url=all_docs_url,
                all_docs_html=all_docs_html,
            )
        else:
            documents = self._download_zip_archive_only(
                all_docs_html=all_docs_html,
                all_docs_url=all_docs_url,
                files_dir=files_dir,
            )
            if not documents:
                raise ParsingError("All documents table parsed to empty list and ZIP-only fallback failed")
        merged_identifiers = self._extract_identifier_mapping(
            "\n".join([case_html, all_docs_html]),
            identifier,
        )
        register_case_id = (
            merged_identifiers.application_number
            or merged_identifiers.publication_number
            or self._derive_case_id(case_url)
        )
        return AcquisitionResult(
            register_case_id=register_case_id,
            identifiers=merged_identifiers,
            documents=documents,
        )

    def _candidate_urls(self, identifier: NormalizedIdentifier) -> Iterable[str]:
        raw = identifier.normalized
        compact = raw.removeprefix("EP")
        yield f"{self.BASE}/application?tab=doclist&number={quote_plus(raw)}&lng=en"
        yield f"{self.BASE}/application?tab=doclist&number={quote_plus(compact)}&lng=en"
        yield f"{self.BASE}/application?number={quote_plus(compact)}"
        yield f"{self.BASE}/application?number={quote_plus(raw)}"
        yield f"{self.BASE}/search?lng=en&query={quote_plus(raw)}"
        yield f"{self.BASE}/search?lng=en&q={quote_plus(raw)}"

    def _resolve_case_page(self, identifier: NormalizedIdentifier) -> tuple[str, str]:
        bypass_attempted = False
        for url in self._candidate_urls(identifier):
            try:
                result = self.fetcher.get(url)
            except NotFoundError:
                continue
            except BlockedError:
                if not bypass_attempted and self.fetcher.try_browser_bypass(url):
                    bypass_attempted = True
                    result = self.fetcher.get(url)
                else:
                    raise
            html = result.text
            if self._looks_blocked(html, str(result.url)):
                if not bypass_attempted and self.fetcher.try_browser_bypass(url):
                    bypass_attempted = True
                    result = self.fetcher.get(url)
                    html = result.text
                if self._looks_blocked(html, str(result.url)):
                    raise BlockedError(
                        "Access to EP Register appears blocked by anti-bot controls"
                    )
            if self._looks_like_case_page(html):
                self.logger.info("Resolved case page: %s", result.url)
                return result.url, html
            linked = self._extract_application_link(html, result.url)
            if linked:
                try:
                    follow = self.fetcher.get(linked)
                except BlockedError:
                    if not bypass_attempted and self.fetcher.try_browser_bypass(linked):
                        bypass_attempted = True
                        follow = self.fetcher.get(linked)
                    else:
                        raise
                if self._looks_blocked(follow.text, str(follow.url)):
                    if not bypass_attempted and self.fetcher.try_browser_bypass(linked):
                        bypass_attempted = True
                        follow = self.fetcher.get(linked)
                    if self._looks_blocked(follow.text, str(follow.url)):
                        raise BlockedError(
                            "Access to EP Register appears blocked by anti-bot controls"
                        )
                if self._looks_like_case_page(follow.text):
                    self.logger.info("Resolved case page via search result: %s", follow.url)
                    return follow.url, follow.text
        raise NotFoundError(
            f"Unable to resolve EP Register case page for {identifier.normalized}"
        )

    def _resolve_all_documents_page(self, case_url: str, case_html: str) -> tuple[str, str]:
        bypass_attempted = False
        if self._contains_documents_table(case_html):
            return case_url, case_html
        soup = BeautifulSoup(case_html, HTML_PARSER)
        anchors = soup.find_all("a")
        for anchor in anchors:
            text = anchor.get_text(" ", strip=True).lower()
            href = anchor.get("href", "")
            if (
                "all documents" in text
                or "file inspection" in text
                or "alldoc" in href.lower()
                or "inspection" in href.lower()
            ):
                url = urljoin(case_url, href)
                try:
                    page = self.fetcher.get(url)
                except BlockedError:
                    if not bypass_attempted and self.fetcher.try_browser_bypass(url):
                        bypass_attempted = True
                        page = self.fetcher.get(url)
                    else:
                        raise
                if self._looks_blocked(page.text, str(page.url)):
                    if not bypass_attempted and self.fetcher.try_browser_bypass(url):
                        bypass_attempted = True
                        page = self.fetcher.get(url)
                    if self._looks_blocked(page.text, str(page.url)):
                        raise BlockedError(
                            "Access to EP Register appears blocked by anti-bot controls"
                        )
                if self._contains_documents_table(page.text):
                    self.logger.info("Resolved all documents page: %s", page.url)
                    return page.url, page.text
        raise UnexpectedHtmlError("Failed to locate All documents / file inspection page link")

    def _download_documents(
        self,
        documents: list[DocumentRecord],
        files_dir: Path,
        *,
        all_docs_url: str,
        all_docs_html: str,
    ) -> None:
        files_dir.mkdir(parents=True, exist_ok=True)
        remaining = list(documents)
        zip_payload = self._extract_zip_archive_payload(all_docs_html, all_docs_url)
        if zip_payload:
            remaining = self._download_via_zip_archive(zip_payload, remaining, files_dir)

        if not remaining:
            return

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(self._download_one, doc, files_dir) for doc in remaining]
            for future in as_completed(futures):
                future.result()

    def _download_one(self, doc: DocumentRecord, files_dir: Path) -> None:
        ext = "pdf" if doc.content_type == "pdf" else "html"
        out_file = files_dir / f"{doc.register_document_id}.{ext}"
        if out_file.exists() and out_file.stat().st_size > 0:
            doc.local_path = str(out_file)
            self.metrics.inc("download_success")
            return
        try:
            result = self.fetcher.get(doc.file_url)
        except Exception as exc:  # noqa: BLE001
            self.metrics.inc("download_fail")
            self.logger.error("Download failed for %s: %s", doc.file_url, exc)
            return
        payload = result.content
        if not payload:
            self.metrics.inc("download_fail")
            self.logger.error("Downloaded empty payload for %s", doc.file_url)
            return
        content_type_header = result.headers.get("content-type", "").lower()
        if "pdf" in content_type_header:
            doc.content_type = "pdf"
        elif "html" in content_type_header:
            doc.content_type = "html"
        out_file.write_bytes(payload)
        doc.local_path = str(out_file)
        self.metrics.inc("download_success")

    def _download_via_zip_archive(
        self,
        payload: ZipArchivePayload,
        documents: list[DocumentRecord],
        files_dir: Path,
    ) -> list[DocumentRecord]:
        extracted_files = self._extract_zip_archive_files(payload, files_dir)
        if not extracted_files:
            return documents

        remaining: list[DocumentRecord] = []
        available = list(extracted_files)

        # First pass: exact match by document identifier in file name.
        for doc in documents:
            matched = self._match_extracted_file(doc, available)
            if not matched:
                remaining.append(doc)
                continue
            self._assign_local_file(doc, matched)
            self.metrics.inc("download_success")
            available.remove(matched)
        return remaining

    def _download_zip_archive_only(
        self,
        *,
        all_docs_html: str,
        all_docs_url: str,
        files_dir: Path,
    ) -> list[DocumentRecord]:
        payload = self._extract_zip_archive_payload(all_docs_html, all_docs_url)
        if not payload:
            return []
        extracted_files = self._extract_zip_archive_files(payload, files_dir)
        if not extracted_files:
            return []

        records: list[DocumentRecord] = []
        seen_ids: set[str] = set()
        for file_path in sorted(extracted_files, key=lambda p: p.name.lower()):
            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                content_type = "pdf"
            elif suffix in {".htm", ".html"}:
                content_type = "html"
            else:
                continue

            base_id = self._normalize_for_match(file_path.stem).replace(" ", "_")
            base_id = re.sub(r"[^a-z0-9_]+", "", base_id.lower()) or "regdoc"
            doc_id = base_id
            idx = 2
            while doc_id in seen_ids:
                doc_id = f"{base_id}_{idx}"
                idx += 1
            seen_ids.add(doc_id)

            records.append(
                DocumentRecord(
                    register_document_id=doc_id,
                    date=None,
                    document_type_raw=file_path.stem,
                    procedure="",
                    pages=0,
                    file_url=str(file_path),
                    content_type=content_type,
                    local_path=str(file_path),
                )
            )
            self.metrics.inc("download_success")
        return records

    def _extract_zip_archive_files(self, payload: ZipArchivePayload, files_dir: Path) -> list[Path]:
        post_data = dict(payload.form_data)
        post_data["documentIdentifiers"] = "+".join(payload.document_ids)
        post_data["number"] = payload.application_number
        post_data.setdefault("unip", "false")
        post_data.setdefault("output", "zip")

        parsed = urlparse(payload.referer_url)
        request_headers = {
            "Accept": "application/zip, application/octet-stream;q=0.9, */*;q=0.8",
            "Origin": f"{parsed.scheme}://{parsed.netloc}",
            "Referer": payload.referer_url,
        }

        result = None
        for attempt in range(2):
            try:
                result = self.fetcher.post_form(payload.action_url, post_data, headers=request_headers)
            except Exception as exc:  # noqa: BLE001
                if attempt == 0 and self.fetcher.try_browser_bypass(payload.referer_url):
                    continue
                self.logger.warning("Zip archive download failed; fallback to per-document: %s", exc)
                return []

            if self._looks_blocked(result.text, result.url):
                if attempt == 0 and self.fetcher.try_browser_bypass(payload.referer_url):
                    result = None
                    continue
                self.logger.warning("Zip archive response appears blocked; fallback to per-document")
                return []
            break

        if result is None:
            return []

        content_type = result.headers.get("content-type", "").lower()
        is_zip = (
            "zip" in content_type
            or result.url.lower().endswith(".zip")
            or result.content.startswith(b"PK\x03\x04")
        )
        if not is_zip or not result.content:
            self.logger.warning("Zip archive response is not a ZIP payload; fallback to per-document")
            return []

        extract_dir = files_dir / "zip_archive"
        tmp_extract_dir = files_dir / ".zip_archive_tmp"
        backup_extract_dir = files_dir / ".zip_archive_prev"
        shutil.rmtree(tmp_extract_dir, ignore_errors=True)
        shutil.rmtree(backup_extract_dir, ignore_errors=True)
        tmp_extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(result.content)) as zf:
                zf.extractall(tmp_extract_dir)
        except zipfile.BadZipFile:
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            self.logger.warning("Invalid ZIP archive payload; fallback to per-document")
            return []

        zip_path = files_dir / "register_selected_documents.zip"
        zip_path.write_bytes(result.content)
        try:
            if extract_dir.exists():
                extract_dir.replace(backup_extract_dir)
            tmp_extract_dir.replace(extract_dir)
        except Exception:
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
            if backup_extract_dir.exists():
                backup_extract_dir.replace(extract_dir)
            shutil.rmtree(tmp_extract_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(backup_extract_dir, ignore_errors=True)

        return [p for p in extract_dir.rglob("*") if p.is_file()]

    @staticmethod
    def _match_extracted_file(doc: DocumentRecord, extracted_files: list[Path]) -> Path | None:
        doc_id = doc.register_document_id.lower()
        for file_path in extracted_files:
            if doc_id and doc_id in file_path.name.lower():
                return file_path
        if not extracted_files:
            return None

        target = RegisterScraper._normalize_for_match(doc.document_type_raw)
        if not target:
            return None
        best_score = 0.0
        best_path: Path | None = None
        for file_path in extracted_files:
            name_norm = RegisterScraper._normalize_for_match(file_path.stem)
            if not name_norm:
                continue
            score = SequenceMatcher(None, target, name_norm).ratio()
            if doc.date and doc.date in file_path.name:
                score += 0.2
            if score > best_score:
                best_score = score
                best_path = file_path
        if best_score >= 0.45:
            return best_path
        return None

    @staticmethod
    def _assign_local_file(doc: DocumentRecord, path: Path) -> None:
        doc.local_path = str(path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            doc.content_type = "pdf"
        elif suffix in {".htm", ".html"}:
            doc.content_type = "html"

    @staticmethod
    def _normalize_for_match(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
        return re.sub(r"\s+", " ", cleaned)

    @staticmethod
    def _extract_zip_archive_payload(html: str, page_url: str) -> ZipArchivePayload | None:
        soup = BeautifulSoup(html, HTML_PARSER)
        zip_form = (
            soup.find("form", attrs={"name": "zipForm"})
            or soup.find("form", attrs={"id": "zipForm"})
            or soup.find("form", attrs={"action": re.compile(r"download", re.IGNORECASE)})
        )
        if not zip_form:
            return None

        action = zip_form.get("action", "").strip() or "download"
        action_url = urljoin(page_url, action)
        form_data: dict[str, str] = {}
        for form_input in zip_form.find_all("input"):
            name = (form_input.get("name") or "").strip()
            if not name:
                continue
            form_data[name] = (form_input.get("value") or "").strip()
        number_input = zip_form.find("input", attrs={"name": "number"})
        application_number = ""
        if number_input:
            application_number = (number_input.get("value") or "").strip()
        if not application_number:
            application_number = form_data.get("number", "").strip()
        if not application_number:
            match = re.search(r"[?&]number=([A-Za-z0-9.]+)", page_url)
            if match:
                application_number = match.group(1)

        document_ids: list[str] = []
        for checkbox in soup.find_all("input"):
            input_type = (checkbox.get("type") or "").strip().lower()
            if input_type and input_type != "checkbox":
                continue
            name = (checkbox.get("name") or "").strip().lower()
            if not (
                name in {"identivier", "identifier", "documentidentifier", "documentidentifiers", "documentid"}
                or "identi" in name
            ):
                continue
            value = (checkbox.get("value") or "").strip()
            if value:
                document_ids.append(value)
        if not document_ids:
            hidden = soup.find("input", attrs={"name": re.compile(r"documentidentifiers?", re.IGNORECASE)})
            if hidden:
                raw = (hidden.get("value") or "").strip()
                if raw:
                    for item in re.split(r"[+,;\s]+", raw):
                        if item:
                            document_ids.append(item)
        document_ids = list(dict.fromkeys(document_ids))
        if not application_number or not document_ids:
            return None
        return ZipArchivePayload(
            action_url=action_url,
            application_number=application_number,
            document_ids=document_ids,
            form_data=form_data,
            referer_url=page_url,
        )

    def _parse_documents_table(self, html: str, page_url: str) -> list[DocumentRecord]:
        soup = BeautifulSoup(html, HTML_PARSER)
        table = self._select_documents_table(soup)
        if table is None:
            raise UnexpectedHtmlError("Unable to find All documents table in page")
        rows = table.find_all("tr")
        if not rows:
            raise ParsingError("Documents table has no rows")
        header_cells = rows[0].find_all(["th", "td"])
        headers = [cell.get_text(" ", strip=True).lower() for cell in header_cells]
        col_idx = self._column_index_map(headers)
        documents: list[DocumentRecord] = []
        for row in rows[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            try:
                date_raw = self._cell_value(cells, col_idx.get("date", 0))
                doc_type_raw = self._cell_value(cells, col_idx.get("document", 1))
                procedure = self._cell_value(cells, col_idx.get("procedure", 2))
                pages_text = self._cell_value(cells, col_idx.get("pages", 3))
                pages = self._parse_pages(pages_text)
                href = self._extract_best_href(row)
                if not href:
                    continue
                file_url = urljoin(page_url, href)
                content_type = "pdf" if href and ".pdf" in href.lower() else "html"
                doc_id = (
                    row.get("data-document-id")
                    or row.get("data-id")
                    or row.get("id")
                    or self._extract_row_document_id(row)
                    or self._derive_document_id(
                        date_raw=date_raw,
                        document_type_raw=doc_type_raw,
                        procedure=procedure,
                        pages=pages,
                        file_url=file_url,
                    )
                )
                documents.append(
                    DocumentRecord(
                        register_document_id=doc_id,
                        date=self._parse_date(date_raw),
                        document_type_raw=doc_type_raw or "Unknown document",
                        procedure=procedure,
                        pages=pages,
                        file_url=file_url,
                        content_type=content_type,
                    )
                )
            except Exception:  # noqa: BLE001
                self.metrics.inc("parse_fail")
                continue
        if not documents:
            raise ParsingError("No parseable document rows found")
        return documents

    @staticmethod
    def _cell_value(cells, idx: int) -> str:
        if idx < 0 or idx >= len(cells):
            return ""
        return cells[idx].get_text(" ", strip=True)

    @staticmethod
    def _column_index_map(headers: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for idx, header in enumerate(headers):
            if "date" in header:
                mapping["date"] = idx
            elif "document" in header:
                mapping["document"] = idx
            elif "procedure" in header:
                mapping["procedure"] = idx
            elif "page" in header:
                mapping["pages"] = idx
        return mapping

    def _select_documents_table(self, soup: BeautifulSoup):
        candidates = soup.find_all("table")
        best = None
        best_score = -1
        for table in candidates:
            score = self._table_score(table)
            if score > best_score:
                best = table
                best_score = score
        if best_score < 2:
            return None
        return best

    def _table_score(self, table) -> int:
        rows = table.find_all("tr")
        if len(rows) < 2:
            return 0
        headers = [h.get_text(" ", strip=True).lower() for h in rows[0].find_all(["th", "td"])]
        text = " ".join(headers)
        score = len(rows)
        table_text = str(table).lower()
        for keyword in ("date", "document", "procedure", "page"):
            if keyword in text:
                score += 2
        if "application?documentid=" in table_text or "documentid=" in table_text or "newpdfwindow(" in table_text:
            score += 6
        if "identivier" in table_text or "identifier" in table_text:
            score += 3
        return score

    @staticmethod
    def _extract_best_href(row) -> str | None:
        links = row.find_all("a")
        if not links:
            return None
        js_pdf_pattern = re.compile(r"newpdfwindow\((?:'|\")([^'\"]+)(?:'|\")", flags=re.IGNORECASE)
        doc_link_pattern = re.compile(
            r"(application\?[^'\"\s>]*documentid=[^'\"\s>]+)",
            flags=re.IGNORECASE,
        )
        for link in links:
            for attr_name in ("href", "onclick"):
                raw_attr = link.get(attr_name)
                if not raw_attr:
                    continue
                normalized_href = raw_attr.replace("&amp;", "&")
                if ".pdf" in normalized_href.lower():
                    return normalized_href
                js_match = js_pdf_pattern.search(normalized_href)
                if js_match:
                    return js_match.group(1).replace("&amp;", "&")
                doc_match = doc_link_pattern.search(normalized_href)
                if doc_match:
                    return doc_match.group(1).replace("&amp;", "&")
        for link in links:
            href = link.get("href")
            if not href:
                continue
            normalized_href = href.replace("&amp;", "&")
            if normalized_href.lower().startswith("javascript:"):
                js_match = js_pdf_pattern.search(normalized_href)
                if js_match:
                    return js_match.group(1).replace("&amp;", "&")
                continue
            if normalized_href:
                return normalized_href
        href = links[0].get("href")
        if href:
            normalized_href = href.replace("&amp;", "&")
            js_match = js_pdf_pattern.search(normalized_href)
            if js_match:
                return js_match.group(1).replace("&amp;", "&")
            if normalized_href and ".pdf" in normalized_href.lower():
                return normalized_href
        row_html = str(row).replace("&amp;", "&")
        doc_match = doc_link_pattern.search(row_html)
        if doc_match:
            return doc_match.group(1)
        return None

    @staticmethod
    def _parse_pages(text: str) -> int:
        match = re.search(r"\d+", text or "")
        return int(match.group(0)) if match else 0

    @staticmethod
    def _parse_date(value: str) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(cleaned, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_row_document_id(row) -> str | None:
        for checkbox in row.find_all("input"):
            name = (checkbox.get("name") or "").strip().lower()
            if not (
                name in {"identivier", "identifier", "documentidentifier", "documentid"}
                or "identi" in name
            ):
                continue
            value = (checkbox.get("value") or "").strip()
            if value:
                return value
        data_document_id = (row.get("data-document-id") or "").strip()
        if data_document_id:
            return data_document_id
        link = row.find("a", id=True)
        if link and link.get("id"):
            return str(link.get("id")).strip() or None
        return None

    @staticmethod
    def _derive_document_id(
        *,
        date_raw: str,
        document_type_raw: str,
        procedure: str,
        pages: int,
        file_url: str,
    ) -> str:
        seed = "|".join([date_raw, document_type_raw, procedure, str(pages), file_url])
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
        return f"regdoc_{digest}"

    def _derive_case_id(self, case_url: str) -> str:
        return f"epcase_{hashlib.sha256(case_url.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _looks_like_case_page(html: str) -> bool:
        lowered = html.lower()
        if "all documents" in lowered or "file inspection" in lowered:
            return True
        return "application number" in lowered and "register" in lowered

    @staticmethod
    def _contains_documents_table(html: str) -> bool:
        lowered = html.lower()
        if "<table" not in lowered:
            return False
        if "application?documentid=" in lowered or "documentid=" in lowered or "newpdfwindow(" in lowered:
            return True
        if "documentid=" in lowered and (
            "ep all documents" in lowered or "document type" in lowered
        ):
            return True
        return (
            ("all documents" in lowered or "doclist" in lowered)
            and ("document type" in lowered or "procedure" in lowered)
        )

    @staticmethod
    def _extract_application_link(html: str, base_url: str) -> str | None:
        soup = BeautifulSoup(html, HTML_PARSER)
        for anchor in soup.find_all("a"):
            href = anchor.get("href", "")
            text = anchor.get_text(" ", strip=True).lower()
            if "application" in href.lower() or "application" in text:
                return urljoin(base_url, href)
        return None

    @staticmethod
    def _looks_blocked(html: str, page_url: str) -> bool:
        lowered = html.lower()
        if "error403.htm?reason=restrictedrequest" in page_url.lower():
            return True
        if "restrictedrequest" in lowered:
            return True
        if "access denied" in lowered:
            return True

        # Cloudflare challenge scripts can co-exist with valid doclist content.
        has_challenge = (
            "cdn-cgi/challenge-platform" in lowered
            or "__cf$cv$params" in lowered
        )
        if not has_challenge:
            return False

        looks_like_doclist = (
            "<table" in lowered
            and "document type" in lowered
            and ("application?documentid=" in lowered or "newpdfwindow(" in lowered)
        )
        return not looks_like_doclist

    def _extract_identifier_mapping(
        self,
        html: str,
        identifier: NormalizedIdentifier,
    ) -> IdentifierMapping:
        text = BeautifulSoup(html, HTML_PARSER).get_text(" ", strip=True).upper()
        app_match = re.search(r"EP\d{8}\.\d", text)
        pub_match = re.search(r"EP\d{7,}(?!\.)", text)
        mapping = IdentifierMapping(
            publication_number=identifier.publication_number,
            application_number=identifier.application_number,
        )
        if app_match:
            mapping.application_number = app_match.group(0)
        if pub_match:
            pub = pub_match.group(0)
            if not mapping.application_number or pub != mapping.application_number.replace(".", ""):
                mapping.publication_number = pub
        return mapping
