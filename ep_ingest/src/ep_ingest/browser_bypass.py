from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ep_ingest.errors import BlockedError


@dataclass
class BrowserWarmupResult:
    final_url: str
    html: str
    cookies: list[dict[str, Any]]


class BrowserBypassProvider(Protocol):
    def warmup(self, url: str) -> BrowserWarmupResult:
        ...


class PlaywrightBypassProvider:
    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 60000,
        proxy: str | None = None,
        user_data_dir: str | None = None,
        user_agent: str | None = None,
        locale: str = "en-US",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.proxy = proxy
        self.user_data_dir = user_data_dir
        self.user_agent = user_agent
        self.locale = locale

    def warmup(self, url: str) -> BrowserWarmupResult:
        try:
            from playwright.sync_api import TimeoutError as PwTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # noqa: BLE001
            raise BlockedError(
                "Browser fallback requires playwright. Install with: "
                "python -m pip install playwright && python -m playwright install chromium"
            ) from exc

        try:
            with sync_playwright() as p:
                launch_kwargs = {"headless": self.headless}
                if self.proxy:
                    launch_kwargs["proxy"] = {"server": self.proxy}
                if self.user_data_dir:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(Path(self.user_data_dir)),
                        locale=self.locale,
                        user_agent=self.user_agent,
                        **launch_kwargs,
                    )
                    browser = None
                else:
                    browser = p.chromium.launch(**launch_kwargs)
                    context = browser.new_context(
                        locale=self.locale,
                        user_agent=self.user_agent,
                    )

                try:
                    context.add_init_script(self._stealth_init_script())
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    self._wait_until_ready(page)
                    html = page.content()
                    cookies = context.cookies()
                    final_url = page.url
                    if "error403.htm?reason=restrictedrequest" in final_url.lower():
                        raise BlockedError(
                            "EP Register is enforcing IP-level restriction (RestrictedRequest). "
                            "Use an allowed egress IP/proxy, then retry."
                        )
                    if self._looks_like_challenge(html):
                        raise BlockedError(
                            "Browser fallback reached a Cloudflare verification page but did not clear it. "
                            "Use a trusted proxy or run with a persistent non-headless browser profile."
                        )
                    return BrowserWarmupResult(final_url=final_url, html=html, cookies=cookies)
                finally:
                    context.close()
                    if browser is not None:
                        browser.close()
        except PwTimeoutError as exc:
            raise BlockedError(f"Browser fallback timed out for {url}") from exc
        except BlockedError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BlockedError(f"Browser fallback failed for {url}") from exc

    def _wait_until_ready(self, page) -> None:
        page.wait_for_timeout(3000)
        step_ms = 1000
        waited = 3000
        while waited < self.timeout_ms:
            html = page.content()
            if not self._looks_like_challenge(html):
                return
            page.wait_for_timeout(step_ms)
            waited += step_ms

    @staticmethod
    def _looks_like_challenge(html: str) -> bool:
        lowered = html.lower()
        challenge_markers = (
            "performing security verification",
            "this website uses a security service to protect against malicious bots",
            "cf-turnstile-response",
            "/cdn-cgi/challenge-platform/",
            "__cf_chl_opt",
            "verification successful. waiting for register.epo.org to respond",
        )
        return any(marker in lowered for marker in challenge_markers)

    @staticmethod
    def _stealth_init_script() -> str:
        return """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
Object.defineProperty(navigator, 'language', {get: () => 'en-US'});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) => (
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : originalQuery(parameters)
  );
}
"""
