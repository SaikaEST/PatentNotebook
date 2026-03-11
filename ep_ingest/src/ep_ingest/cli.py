from __future__ import annotations

from pathlib import Path

import typer

from ep_ingest.errors import IngestError
from ep_ingest.ops_client import OpsClient
from ep_ingest.ops_exam_files import OpsExamFileService
from ep_ingest.service import EpIngestionService

app = typer.Typer(help="EP-only prosecution ingestion (Module 1 + Module 2).")


def _build_service(
    concurrency: int,
    delay: float,
    log_level: str,
    browser_fallback: bool,
    proxy: str | None,
    browser_headless: bool,
    browser_user_data_dir: Path | None,
) -> EpIngestionService:
    return EpIngestionService(
        concurrency=concurrency,
        delay_seconds=delay,
        log_level=log_level,
        browser_fallback=browser_fallback,
        proxy=proxy,
        browser_headless=browser_headless,
        browser_user_data_dir=str(browser_user_data_dir) if browser_user_data_dir else None,
    )


@app.command("fetch")
def fetch_command(
    id: str = typer.Option(..., "--id", help="EP publication or application number."),
    out: Path = typer.Option(Path("data"), "--out", help="Output root directory."),
    concurrency: int = typer.Option(2, "--concurrency"),
    delay: float = typer.Option(0.5, "--delay"),
    log_level: str = typer.Option("INFO", "--log-level"),
    browser_fallback: bool = typer.Option(
        True, "--browser-fallback/--no-browser-fallback"
    ),
    browser_headless: bool = typer.Option(
        True, "--browser-headless/--browser-headed"
    ),
    browser_user_data_dir: Path | None = typer.Option(
        None, "--browser-user-data-dir", help="Persistent browser profile directory."
    ),
    proxy: str | None = typer.Option(None, "--proxy", help="HTTP(S) proxy URL."),
) -> None:
    try:
        dataset = _build_service(
            concurrency, delay, log_level, browser_fallback, proxy, browser_headless, browser_user_data_dir
        ).fetch(id, out)
        typer.echo(
            f"Fetched {len(dataset.documents)} documents for {dataset.patent_id} "
            f"(register_case_id={dataset.register_case_id})"
        )
    except IngestError as exc:
        typer.echo(f"Error [{exc.error_code}]: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command("run")
def run_command(
    id: str = typer.Option(..., "--id", help="EP publication or application number."),
    out: Path = typer.Option(Path("data"), "--out", help="Output root directory."),
    concurrency: int = typer.Option(2, "--concurrency"),
    delay: float = typer.Option(0.5, "--delay"),
    log_level: str = typer.Option("INFO", "--log-level"),
    browser_fallback: bool = typer.Option(
        True, "--browser-fallback/--no-browser-fallback"
    ),
    browser_headless: bool = typer.Option(
        True, "--browser-headless/--browser-headed"
    ),
    browser_user_data_dir: Path | None = typer.Option(
        None, "--browser-user-data-dir", help="Persistent browser profile directory."
    ),
    proxy: str | None = typer.Option(None, "--proxy", help="HTTP(S) proxy URL."),
) -> None:
    try:
        dataset = _build_service(
            concurrency, delay, log_level, browser_fallback, proxy, browser_headless, browser_user_data_dir
        ).run(id, out)
        typer.echo(
            f"Completed run for {dataset.patent_id}: "
            f"{len(dataset.documents)} docs, {len(dataset.timeline)} timeline entries"
        )
    except IngestError as exc:
        typer.echo(f"Error [{exc.error_code}]: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command("timeline")
def timeline_command(
    id: str = typer.Option(..., "--id", help="EP publication or application number."),
    out: Path = typer.Option(Path("data"), "--out", help="Output root directory."),
    concurrency: int = typer.Option(2, "--concurrency"),
    delay: float = typer.Option(0.5, "--delay"),
    log_level: str = typer.Option("INFO", "--log-level"),
    browser_fallback: bool = typer.Option(
        True, "--browser-fallback/--no-browser-fallback"
    ),
    browser_headless: bool = typer.Option(
        True, "--browser-headless/--browser-headed"
    ),
    browser_user_data_dir: Path | None = typer.Option(
        None, "--browser-user-data-dir", help="Persistent browser profile directory."
    ),
    proxy: str | None = typer.Option(None, "--proxy", help="HTTP(S) proxy URL."),
) -> None:
    try:
        dataset = _build_service(
            concurrency, delay, log_level, browser_fallback, proxy, browser_headless, browser_user_data_dir
        ).rebuild_timeline(id, out)
        typer.echo(
            f"Rebuilt timeline for {dataset.patent_id}: {len(dataset.timeline)} entries"
        )
    except IngestError as exc:
        typer.echo(f"Error [{exc.error_code}]: {exc}", err=True)
        raise typer.Exit(code=1)


@app.command("fetch-ops")
def fetch_ops_command(
    id: str = typer.Option(..., "--id", help="EP publication or application number."),
    out: Path = typer.Option(Path("data"), "--out", help="Output root directory."),
    ops_key: str = typer.Option(
        "",
        "--ops-key",
        envvar="EPO_OPS_KEY",
        help="OPS consumer key (or env EPO_OPS_KEY).",
    ),
    ops_secret: str = typer.Option(
        "",
        "--ops-secret",
        envvar="EPO_OPS_SECRET",
        help="OPS consumer secret (or env EPO_OPS_SECRET).",
    ),
    timeout: float = typer.Option(30.0, "--timeout"),
    download: bool = typer.Option(
        True,
        "--download/--no-download",
        help="Download retrieved OPS image documents as PDF.",
    ),
    max_files: int = typer.Option(10, "--max-files", min=0),
) -> None:
    if not ops_key or not ops_secret:
        typer.echo(
            "Missing OPS credentials. Set --ops-key/--ops-secret or env "
            "EPO_OPS_KEY and EPO_OPS_SECRET.",
            err=True,
        )
        raise typer.Exit(code=1)
    client = OpsClient(key=ops_key, secret=ops_secret, timeout_seconds=timeout)
    try:
        result = OpsExamFileService(ops_client=client).fetch(
            identifier=id,
            out_dir=out,
            download=download,
            max_files=max_files,
        )
    except IngestError as exc:
        typer.echo(f"Error [{exc.error_code}]: {exc}", err=True)
        raise typer.Exit(code=1)
    finally:
        client.close()

    typer.echo(
        f"OPS fetch completed for {result['patent_id']}: "
        f"{len(result['examination_events'])} exam events, "
        f"{len(result['files'])} file candidates"
    )


if __name__ == "__main__":
    app()
