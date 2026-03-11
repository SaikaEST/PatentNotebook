from __future__ import annotations

from pathlib import Path

import httpx

from ep_ingest.browser_bypass import BrowserWarmupResult
from ep_ingest.http_client import HttpFetcher


def test_http_fetcher_etag_cache(tmp_path: Path) -> None:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if request.headers.get("if-none-match") == "abc123":
            return httpx.Response(status_code=304)
        return httpx.Response(
            status_code=200,
            headers={"ETag": "abc123", "Content-Type": "text/html"},
            text="<html>ok</html>",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = HttpFetcher(cache_dir=tmp_path / "cache", delay_seconds=0, client=client)
    first = fetcher.get("https://register.epo.org/example")
    second = fetcher.get("https://register.epo.org/example")
    fetcher.close()

    assert first.from_cache is False
    assert second.from_cache is True
    assert first.content == second.content
    assert state["calls"] == 2


def test_http_fetcher_uses_browser_cache_when_followup_request_is_blocked(tmp_path: Path) -> None:
    class _BypassProvider:
        def warmup(self, url: str) -> BrowserWarmupResult:
            return BrowserWarmupResult(
                final_url=url,
                html="<html>All documents</html>",
                cookies=[{"name": "cf_clearance", "value": "ok", "domain": "register.epo.org", "path": "/"}],
            )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=403, text="forbidden")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = HttpFetcher(
        cache_dir=tmp_path / "cache",
        delay_seconds=0,
        client=client,
        browser_bypass_provider=_BypassProvider(),
    )

    assert fetcher.try_browser_bypass("https://register.epo.org/example") is True
    result = fetcher.get("https://register.epo.org/example")
    fetcher.close()

    assert result.from_cache is True
    assert result.status_code == 200
    assert result.text == "<html>All documents</html>"
