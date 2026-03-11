from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from ep_ingest.browser_bypass import BrowserBypassProvider
from ep_ingest.identifiers import normalize_identifier
from ep_ingest.logging_utils import configure_logging, get_logger, new_correlation_id
from ep_ingest.metrics import Metrics
from ep_ingest.models import DocumentRecord, PatentDataset
from ep_ingest.processing.comparison_candidates import export_comparison_candidates
from ep_ingest.processing.classify import classify_document
from ep_ingest.processing.extract import extract_text
from ep_ingest.processing.timeline import build_timeline, timeline_to_markdown
from ep_ingest.scraper.register import RegisterScraper
from ep_ingest.storage import build_output_paths, read_json, write_json
from ep_ingest.http_client import HttpFetcher
from ep_ingest.storage import OutputPaths


class EpIngestionService:
    def __init__(
        self,
        *,
        delay_seconds: float = 0.5,
        concurrency: int = 2,
        log_level: str = "INFO",
        browser_fallback: bool = True,
        proxy: str | None = None,
        browser_headless: bool = True,
        browser_user_data_dir: str | None = None,
        browser_bypass_provider: BrowserBypassProvider | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        configure_logging(level=log_level)
        self.delay_seconds = delay_seconds
        self.concurrency = concurrency
        self.browser_fallback = browser_fallback
        self.proxy = proxy
        self.browser_headless = browser_headless
        self.browser_user_data_dir = browser_user_data_dir
        self.browser_bypass_provider = browser_bypass_provider
        self.http_client = http_client

    def fetch(self, identifier: str, out_dir: str | Path = "data") -> PatentDataset:
        correlation_id = new_correlation_id()
        logger = get_logger("ep_ingest.fetch", correlation_id)
        dataset, paths, _ = self._acquire(identifier, out_dir, logger)
        write_json(paths.documents_json, dataset.model_dump(mode="json"))
        export_comparison_candidates(dataset.documents, paths.files_dir)
        logger.info("Wrote documents: %s", paths.documents_json)
        return dataset

    def run(self, identifier: str, out_dir: str | Path = "data") -> PatentDataset:
        correlation_id = new_correlation_id()
        logger = get_logger("ep_ingest.run", correlation_id)
        dataset, paths, metrics = self._acquire(identifier, out_dir, logger)

        for document in dataset.documents:
            if not document.local_path:
                metrics.inc("parse_fail")
                continue
            try:
                document.raw_text = extract_text(document.content_type, document.local_path)
                text_path = paths.text_dir / f"{document.register_document_id}.txt"
                text_path.write_text(document.raw_text, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                metrics.inc("parse_fail")
                logger.error("Text extraction failed for %s: %s", document.register_document_id, exc)
                document.raw_text = ""

            try:
                document.doc_type_norm = classify_document(
                    document.document_type_raw, document.raw_text
                )
            except Exception as exc:  # noqa: BLE001
                metrics.inc("classify_fail")
                logger.error("Classification failed for %s: %s", document.register_document_id, exc)
                document.doc_type_norm = "other"

        dataset.timeline = build_timeline(dataset.documents)
        dataset.generated_at = date.today()
        dataset.metrics = metrics.as_dict()
        write_json(paths.documents_json, dataset.model_dump(mode="json"))
        export_comparison_candidates(dataset.documents, paths.files_dir)
        write_json(
            paths.timeline_json,
            [entry.model_dump(mode="json") for entry in dataset.timeline],
        )
        paths.timeline_md.write_text(timeline_to_markdown(dataset.timeline), encoding="utf-8")
        logger.info("Wrote timeline: %s", paths.timeline_json)
        return dataset

    def rebuild_timeline(self, identifier: str, out_dir: str | Path = "data") -> PatentDataset:
        normalized = normalize_identifier(identifier)
        paths = build_output_paths(Path(out_dir), normalized.patent_id, jurisdiction="EP")
        payload = read_json(paths.documents_json)
        dataset = PatentDataset.model_validate(payload)
        for document in dataset.documents:
            try:
                document.doc_type_norm = classify_document(
                    document.document_type_raw, document.raw_text
                )
            except Exception:  # noqa: BLE001
                document.doc_type_norm = "other"
        dataset.timeline = build_timeline(dataset.documents)
        write_json(
            paths.timeline_json,
            [entry.model_dump(mode="json") for entry in dataset.timeline],
        )
        paths.timeline_md.write_text(timeline_to_markdown(dataset.timeline), encoding="utf-8")
        return dataset

    def _acquire(
        self, identifier: str, out_dir: str | Path, logger
    ) -> tuple[PatentDataset, OutputPaths, Metrics]:
        normalized = normalize_identifier(identifier)
        metrics = Metrics()
        paths = build_output_paths(Path(out_dir), normalized.patent_id, jurisdiction="EP")

        fetcher = HttpFetcher(
            cache_dir=paths.cache_dir,
            delay_seconds=self.delay_seconds,
            enable_browser_fallback=self.browser_fallback,
            proxy=self.proxy,
            browser_headless=self.browser_headless,
            browser_user_data_dir=self.browser_user_data_dir,
            browser_bypass_provider=self.browser_bypass_provider,
            client=self.http_client,
        )
        should_close = self.http_client is None
        try:
            scraper = RegisterScraper(
                fetcher=fetcher,
                metrics=metrics,
                logger=logger,
                concurrency=self.concurrency,
            )
            acquired = scraper.acquire(normalized, paths.files_dir)
        finally:
            if should_close:
                fetcher.close()

        dataset = PatentDataset(
            patent_id=normalized.patent_id,
            jurisdiction="EP",
            register_case_id=acquired.register_case_id,
            identifiers=acquired.identifiers,
            documents=acquired.documents,
            metrics=metrics.as_dict(),
        )
        return dataset, paths, metrics


def load_documents(path: Path) -> list[DocumentRecord]:
    payload = read_json(path)
    dataset = PatentDataset.model_validate(payload)
    return dataset.documents
