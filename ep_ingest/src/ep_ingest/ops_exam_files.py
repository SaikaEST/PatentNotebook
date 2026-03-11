from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ep_ingest.errors import BlockedError, NetworkError, NotFoundError, ParsingError
from ep_ingest.identifiers import normalize_identifier
from ep_ingest.models import NormalizedIdentifier
from ep_ingest.ops_client import OpsClient
from ep_ingest.storage import build_output_paths, write_json

_EVENT_KEYWORDS = (
    "examination",
    "search report",
    "supplementary search",
    "communication",
    "reply",
    "response",
    "office action",
    "amendment",
    "refusal",
    "grant",
    "article 94",
    "article 96",
)
_EVENT_EXCLUDE_KEYWORDS = (
    "validation of the patent",
    "extension of the patent",
    "language of the procedure",
)

_PUB_REF_RE = re.compile(r"\bEP\d{7,}[A-Z]\d?\b", re.IGNORECASE)
_PUB_KIND_ALLOWED = set("ABCUTWY")


@dataclass
class RegisterSnapshot:
    reference_type: str
    epodoc_input: str
    payloads: dict[str, str]


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def _norm_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _parse_date(value: str | None) -> str | None:
    raw = _norm_text(value)
    if not raw:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _is_exam_related(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _EVENT_KEYWORDS)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _extract_ops_image_path(href: str) -> str | None:
    text = _norm_text(href)
    if not text:
        return None
    marker = "/published-data/images/"
    idx = text.lower().find(marker)
    if idx >= 0:
        return text[idx + len(marker) :].lstrip("/")
    if text.startswith(("EP/", "WO/", "US/")):
        return text
    parsed = urlparse(text)
    if parsed.path and "/published-data/images/" in parsed.path.lower():
        idx = parsed.path.lower().find(marker)
        return parsed.path[idx + len(marker) :].lstrip("/")
    return None


class OpsExamFileService:
    def __init__(self, *, ops_client: OpsClient, logger=None) -> None:
        self.ops_client = ops_client
        self.logger = logger

    def fetch(
        self,
        *,
        identifier: str,
        out_dir: str | Path = "data",
        download: bool = True,
        max_files: int = 10,
    ) -> dict:
        normalized = normalize_identifier(identifier)
        register_snapshot = self._fetch_register_snapshot(normalized)

        register_text_joined = "\n".join(register_snapshot.payloads.values())
        all_events = self._extract_all_events(register_snapshot.payloads)
        examination_events = self._filter_examination_events(all_events)
        publication_refs = self._collect_publication_refs(
            normalized,
            register_text_joined,
            register_snapshot.payloads,
        )
        image_candidates = self._collect_image_candidates(publication_refs)
        if not image_candidates:
            image_candidates = self._build_heuristic_image_candidates(publication_refs)

        paths = build_output_paths(Path(out_dir), normalized.patent_id, jurisdiction="EP")
        ops_dir = paths.jurisdiction_dir / "ops_exam"
        files_dir = ops_dir / "files"
        ops_dir.mkdir(parents=True, exist_ok=True)
        files_dir.mkdir(parents=True, exist_ok=True)

        downloaded_files: list[dict] = []
        for idx, candidate in enumerate(image_candidates[: max(0, max_files)], start=1):
            record = dict(candidate)
            if download:
                filename = (
                    f"ops_{idx:03d}_{candidate['publication_ref']}_"
                    f"{_slug(candidate['description']) or 'document'}.pdf"
                )
                output_path = files_dir / filename
                try:
                    payload = self.ops_client.published_image_retrieval(
                        image_path=candidate["image_path"],
                        page=1,
                        accept="application/pdf",
                    )
                    output_path.write_bytes(payload)
                    record["local_path"] = str(output_path)
                except Exception as exc:  # noqa: BLE001
                    record["error"] = str(exc)
            downloaded_files.append(record)

        # Keep raw XML for troubleshooting and reproducibility.
        for endpoint, xml_text in register_snapshot.payloads.items():
            (ops_dir / f"register_{endpoint}.xml").write_text(xml_text, encoding="utf-8")

        # Persist all events as standalone local artifacts.
        write_json(ops_dir / "all_events.json", all_events)
        (ops_dir / "all_events.md").write_text(
            self._events_to_markdown(
                title="All Register Events",
                patent_id=normalized.patent_id,
                identifier=identifier,
                events=all_events,
            ),
            encoding="utf-8",
        )

        # Persist examination events as standalone local artifacts.
        write_json(ops_dir / "examination_events.json", examination_events)
        (ops_dir / "examination_events.md").write_text(
            self._events_to_markdown(
                title="Examination Events",
                patent_id=normalized.patent_id,
                identifier=identifier,
                events=examination_events,
            ),
            encoding="utf-8",
        )

        result = {
            "patent_id": normalized.patent_id,
            "identifier_input": identifier,
            "register_reference_type": register_snapshot.reference_type,
            "register_epodoc_input": register_snapshot.epodoc_input,
            "publication_refs_tried": publication_refs,
            "all_events": all_events,
            "examination_events": examination_events,
            "files": downloaded_files,
            "download_enabled": download,
        }
        write_json(ops_dir / "ops_exam_files.json", result)
        return result

    def _fetch_register_snapshot(self, normalized: NormalizedIdentifier) -> RegisterSnapshot:
        reference_order = self._reference_order(normalized.kind)
        epodoc_candidates = self._epodoc_candidates(normalized)

        for reference_type in reference_order:
            for epodoc_input in epodoc_candidates:
                payloads: dict[str, str] = {}
                for endpoint in ("events", "procedural-steps", "biblio"):
                    try:
                        payloads[endpoint] = self.ops_client.register_endpoint(
                            reference_type=reference_type,
                            epodoc_input=epodoc_input,
                            endpoint=endpoint,
                        )
                    except NotFoundError:
                        continue
                if payloads:
                    return RegisterSnapshot(
                        reference_type=reference_type,
                        epodoc_input=epodoc_input,
                        payloads=payloads,
                    )

        tried = ", ".join(
            f"{ref}:{epo}" for ref in reference_order for epo in epodoc_candidates
        )
        raise NotFoundError(f"No register data found for {normalized.normalized} (tried {tried})")

    @staticmethod
    def _reference_order(kind: str) -> list[str]:
        if kind == "application":
            return ["application", "publication"]
        if kind == "publication":
            return ["publication", "application"]
        return ["publication", "application"]

    @staticmethod
    def _epodoc_candidates(normalized: NormalizedIdentifier) -> list[str]:
        raw = normalized.normalized.upper().replace(" ", "")
        if raw.startswith("EP"):
            raw_no_prefix = raw[2:]
        else:
            raw_no_prefix = raw
        no_dot = raw_no_prefix.replace(".", "")
        candidates = [f"EP{no_dot}"]
        if "." in raw_no_prefix:
            main_part = raw_no_prefix.split(".", 1)[0]
            candidates.append(f"EP{main_part}")
        return list(dict.fromkeys([c for c in candidates if c and c != "EP"]))

    def _extract_all_events(self, payloads: dict[str, str]) -> list[dict]:
        events: list[dict] = []
        seen: set[tuple[str | None, str]] = set()
        for source, xml_text in payloads.items():
            root = self._parse_xml(xml_text, source_hint=source)
            for node in root.iter():
                local = _local_name(node.tag)
                if local not in {
                    "event",
                    "event-data",
                    "dossier-event",
                    "procedural-step",
                    "procedure-step",
                }:
                    continue
                date_value: str | None = None
                chunks: list[str] = []
                for child in node.iter():
                    child_local = _local_name(child.tag)
                    text = _norm_text(child.text)
                    if not text:
                        continue
                    if "date" in child_local and date_value is None:
                        date_value = _parse_date(text) or text
                        continue
                    if any(
                        token in child_local
                        for token in (
                            "text",
                            "title",
                            "description",
                            "code",
                            "type",
                            "name",
                        )
                    ):
                        chunks.append(text)
                detail = " | ".join(dict.fromkeys(chunks))
                if not detail:
                    continue
                key = (date_value, detail)
                if key in seen:
                    continue
                seen.add(key)
                events.append(
                    {
                        "source": source,
                        "date": date_value,
                        "detail": detail,
                    }
                )

        events.sort(key=lambda item: (item.get("date") or "9999-99-99", item.get("detail") or ""))
        return events

    @staticmethod
    def _filter_examination_events(all_events: list[dict]) -> list[dict]:
        filtered: list[dict] = []
        for event in all_events:
            detail = _norm_text(event.get("detail"))
            lowered_detail = detail.lower()
            if any(token in lowered_detail for token in _EVENT_EXCLUDE_KEYWORDS):
                continue
            if not _is_exam_related(detail):
                continue
            filtered.append(event)
        return filtered

    def _collect_publication_refs(
        self,
        normalized: NormalizedIdentifier,
        register_text: str,
        payloads: dict[str, str],
    ) -> list[str]:
        refs: list[str] = []
        biblio = payloads.get("biblio")
        if biblio:
            root = self._parse_xml(biblio, source_hint="biblio")
            for node in root.iter():
                if _local_name(node.tag) != "document-id":
                    continue
                country = ""
                doc_number = ""
                kind = ""
                for child in node:
                    child_local = _local_name(child.tag)
                    text = _norm_text(child.text).upper()
                    if child_local == "country":
                        country = text
                    elif child_local == "doc-number":
                        doc_number = text
                    elif child_local == "kind":
                        kind = text
                if country == "EP" and doc_number and kind and kind[0] in _PUB_KIND_ALLOWED:
                    refs.append(f"EP{doc_number}{kind}")

        for match in _PUB_REF_RE.finditer(register_text):
            ref = match.group(0).upper()
            kind = ref[-1]
            if kind in _PUB_KIND_ALLOWED:
                refs.append(ref)
        if normalized.publication_number:
            refs.append(normalized.publication_number.replace(".", "").upper())
        return list(dict.fromkeys(refs))

    def _collect_image_candidates(self, publication_refs: Iterable[str]) -> list[dict]:
        candidates: list[dict] = []
        seen_paths: set[str] = set()
        for publication_ref in publication_refs:
            try:
                xml_text = self.ops_client.published_images_inquiry(
                    reference_type="publication",
                    epodoc_input=publication_ref,
                )
            except (NotFoundError, NetworkError, BlockedError) as exc:
                if self.logger:
                    self.logger.warning(
                        "Skip image inquiry for %s due to OPS error: %s",
                        publication_ref,
                        exc,
                    )
                continue
            root = self._parse_xml(xml_text, source_hint=f"images:{publication_ref}")
            for node in root.iter():
                if _local_name(node.tag) != "document-instance":
                    continue
                desc = _norm_text(
                    node.attrib.get("desc")
                    or node.attrib.get("document-description")
                    or node.attrib.get("document-type")
                    or node.attrib.get("type")
                )
                href = ""
                for child in node.iter():
                    for attr_name, attr_value in child.attrib.items():
                        if attr_name.lower().endswith("href"):
                            href = _norm_text(attr_value)
                            if href:
                                break
                    if href:
                        break
                image_path = _extract_ops_image_path(href)
                if not image_path or image_path in seen_paths:
                    continue
                seen_paths.add(image_path)
                candidates.append(
                    {
                        "publication_ref": publication_ref,
                        "description": desc or "document-instance",
                        "href": href,
                        "image_path": image_path,
                    }
                )
        return candidates

    @staticmethod
    def _build_heuristic_image_candidates(publication_refs: Iterable[str]) -> list[dict]:
        candidates: list[dict] = []
        seen_paths: set[str] = set()
        for publication_ref in publication_refs:
            ref = publication_ref.upper().replace(" ", "")
            match = re.match(r"^EP(\d+)([A-Z]\d?)?$", ref)
            if not match:
                continue
            doc_number = match.group(1)
            kind = match.group(2) or "A1"
            for suffix, desc in (
                ("fullimage", "heuristic_fullimage"),
                ("firstpage", "heuristic_firstpage"),
            ):
                image_path = f"EP/{doc_number}/{kind}/{suffix}"
                if image_path in seen_paths:
                    continue
                seen_paths.add(image_path)
                candidates.append(
                    {
                        "publication_ref": publication_ref,
                        "description": desc,
                        "href": f"/rest-services/published-data/images/{image_path}",
                        "image_path": image_path,
                    }
                )
        return candidates

    @staticmethod
    def _parse_xml(xml_text: str, *, source_hint: str) -> ET.Element:
        try:
            return ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise ParsingError(f"Failed to parse XML from OPS ({source_hint})") from exc

    @staticmethod
    def _events_to_markdown(
        *,
        title: str,
        patent_id: str,
        identifier: str,
        events: list[dict],
    ) -> str:
        lines = [
            f"# {title}",
            "",
            f"- patent_id: `{patent_id}`",
            f"- identifier_input: `{identifier}`",
            f"- total_events: `{len(events)}`",
            "",
            "| date | source | detail |",
            "| --- | --- | --- |",
        ]
        if not events:
            lines.append("| - | - | No examination-related events found |")
            return "\n".join(lines) + "\n"

        for event in events:
            date = _norm_text(event.get("date")) or "-"
            source = _norm_text(event.get("source")) or "-"
            detail = _norm_text(event.get("detail")).replace("|", "\\|")
            lines.append(f"| {date} | {source} | {detail} |")
        return "\n".join(lines) + "\n"
