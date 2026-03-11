import logging

from ep_ingest.errors import BlockedError
from ep_ingest.metrics import Metrics
from ep_ingest.models import NormalizedIdentifier
from ep_ingest.scraper.register import RegisterScraper


def test_blocked_page_detection() -> None:
    html = "<html><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"
    assert RegisterScraper._looks_blocked(html, "https://register.epo.org/application?number=EP1")


def test_challenge_script_with_real_doclist_not_blocked() -> None:
    html = """
<html>
  <script>
    window.__CF$cv$params={r:'abc',t:'123'};
    var a=document.createElement('script');
    a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';
  </script>
  <table class="application docList">
    <thead><tr><th>Date</th><th>Document type</th><th>Procedure</th></tr></thead>
    <tbody>
      <tr>
        <td>12.01.2026</td>
        <td><a href="javascript:NewPDFWindow('application?documentId=ABC&amp;number=EP25187001&amp;lng=en&amp;npl=false', 'x')">European search report</a></td>
        <td>Search / examination</td>
      </tr>
    </tbody>
  </table>
</html>
"""
    assert not RegisterScraper._looks_blocked(
        html, "https://register.epo.org/application?tab=doclist&number=EP25187001&lng=en"
    )


def test_resolve_case_page_retries_with_browser_bypass_after_403() -> None:
    class _Fetcher:
        def __init__(self) -> None:
            self.calls = 0
            self.bypass_calls = 0

        def get(self, url: str):
            self.calls += 1
            if self.calls == 1:
                raise BlockedError("Blocked by remote service (403)")

            class _Result:
                url = "https://register.epo.org/application?tab=doclist&number=EP17893014&lng=en"
                text = "<html><body><h1>Register</h1><div>Application number</div><div>All documents</div></body></html>"

            return _Result()

        def try_browser_bypass(self, url: str) -> bool:
            self.bypass_calls += 1
            return True

    scraper = RegisterScraper(
        fetcher=_Fetcher(),
        metrics=Metrics(),
        logger=logging.getLogger(__name__),
        concurrency=1,
    )

    url, html = scraper._resolve_case_page(
        NormalizedIdentifier(normalized="EP17893014", kind="publication", publication_number="EP17893014")
    )

    assert "EP17893014" in url
    assert "Application number" in html
