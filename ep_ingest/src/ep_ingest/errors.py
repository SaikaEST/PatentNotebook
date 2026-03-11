from __future__ import annotations


class IngestError(Exception):
    error_code = "ingest_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class NetworkError(IngestError):
    error_code = "network"


class ParsingError(IngestError):
    error_code = "parsing"


class UnexpectedHtmlError(IngestError):
    error_code = "unexpected_html"


class BlockedError(IngestError):
    error_code = "blocked"


class NotFoundError(IngestError):
    error_code = "not_found"
