from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ep_ingest.browser_bypass import BrowserBypassProvider, PlaywrightBypassProvider
from ep_ingest.errors import BlockedError, NetworkError, NotFoundError


@dataclass
class HttpResult:
    url: str
    status_code: int
    content: bytes
    headers: dict[str, str]
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class HttpFetcher:
    def __init__(
        self,
        *,
        cache_dir: Path,
        delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        enable_browser_fallback: bool = True,
        proxy: str | None = None,
        browser_headless: bool = True,
        browser_user_data_dir: str | None = None,
        browser_bypass_provider: BrowserBypassProvider | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
            proxy=proxy,
        )
        if browser_bypass_provider is not None:
            self.browser_bypass_provider = browser_bypass_provider
        elif enable_browser_fallback:
            self.browser_bypass_provider = PlaywrightBypassProvider(
                headless=browser_headless,
                proxy=proxy,
                user_data_dir=browser_user_data_dir,
                user_agent=user_agent,
            )
        else:
            self.browser_bypass_provider = None

    def close(self) -> None:
        self.client.close()

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        body_path = self.cache_dir / f"{key}.bin"
        meta_path = self.cache_dir / f"{key}.json"
        return body_path, meta_path

    def _wait_rate_limit(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed:
                time.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self.delay_seconds

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type(NetworkError),
    )
    def _request_with_retry(
        self, url: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        self._wait_rate_limit()
        try:
            response = self.client.get(url, headers=headers)
        except httpx.RequestError as exc:
            raise NetworkError(f"Network request failed for {url}") from exc
        if response.status_code >= 500:
            raise NetworkError(f"Server error status={response.status_code} for {url}")
        return response

    def get(self, url: str) -> HttpResult:
        body_path, meta_path = self._cache_paths(url)
        request_headers: dict[str, str] = {}
        cached_headers: dict[str, Any] = {}
        if meta_path.exists():
            cached_headers = json.loads(meta_path.read_text(encoding="utf-8"))
            etag = cached_headers.get("etag")
            last_modified = cached_headers.get("last_modified")
            if etag:
                request_headers["If-None-Match"] = etag
            if last_modified:
                request_headers["If-Modified-Since"] = last_modified
        try:
            response = self._request_with_retry(url, headers=request_headers or None)
        except NetworkError:
            if body_path.exists() and cached_headers:
                return HttpResult(
                    url=url,
                    status_code=200,
                    content=body_path.read_bytes(),
                    headers={k: str(v) for k, v in cached_headers.items()},
                    from_cache=True,
                )
            raise
        if response.status_code == 304:
            if not body_path.exists():
                raise NetworkError(f"Received 304 but cache body missing for {url}")
            return HttpResult(
                url=url,
                status_code=200,
                content=body_path.read_bytes(),
                headers={k: str(v) for k, v in cached_headers.items()},
                from_cache=True,
            )
        if response.status_code in (401, 403, 429):
            if body_path.exists() and cached_headers:
                return HttpResult(
                    url=str(cached_headers.get("url") or url),
                    status_code=200,
                    content=body_path.read_bytes(),
                    headers={k: str(v) for k, v in cached_headers.items()},
                    from_cache=True,
                )
            raise BlockedError(f"Blocked by remote service ({response.status_code})")
        if response.status_code == 404:
            raise NotFoundError(f"Not found: {url}")
        if response.status_code >= 400:
            raise NetworkError(f"Unexpected status={response.status_code} for {url}")

        payload = response.content
        content_hash = hashlib.sha256(payload).hexdigest()
        body_path.write_bytes(payload)
        meta = {
            "url": str(response.url),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "content_type": response.headers.get("Content-Type", ""),
            "content_hash": content_hash,
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return HttpResult(
            url=str(response.url),
            status_code=response.status_code,
            content=payload,
            headers={k.lower(): v for k, v in response.headers.items()},
            from_cache=False,
        )

    def post_form(
        self,
        url: str,
        form_data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> HttpResult:
        self._wait_rate_limit()
        merged_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if headers:
            merged_headers.update(headers)
        try:
            response = self.client.post(url, data=form_data, headers=merged_headers)
        except httpx.RequestError as exc:
            raise NetworkError(f"Network request failed for {url}") from exc

        if response.status_code in (401, 403, 429):
            raise BlockedError(f"Blocked by remote service ({response.status_code})")
        if response.status_code == 404:
            raise NotFoundError(f"Not found: {url}")
        if response.status_code >= 400:
            raise NetworkError(f"Unexpected status={response.status_code} for {url}")

        return HttpResult(
            url=str(response.url),
            status_code=response.status_code,
            content=response.content,
            headers={k.lower(): v for k, v in response.headers.items()},
            from_cache=False,
        )

    def try_browser_bypass(self, url: str) -> bool:
        if self.browser_bypass_provider is None:
            return False
        result = self.browser_bypass_provider.warmup(url)
        for cookie in result.cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if not name or value is None:
                continue
            self.client.cookies.set(
                name=name,
                value=value,
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
        if result.html:
            body_path, meta_path = self._cache_paths(url)
            encoded = result.html.encode("utf-8", errors="replace")
            body_path.write_bytes(encoded)
            meta = {
                "url": result.final_url or url,
                "etag": None,
                "last_modified": None,
                "content_type": "text/html;charset=utf-8",
                "content_hash": hashlib.sha256(encoded).hexdigest(),
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return True
