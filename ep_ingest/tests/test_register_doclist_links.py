from bs4 import BeautifulSoup

from ep_ingest.scraper.register import RegisterScraper


def test_extract_best_href_from_new_pdf_window_javascript() -> None:
    html = """
<tr>
  <td class="nowrap">
    <a id="ABC" href="javascript:NewPDFWindow('application?documentId=ABC&amp;number=EP25187001&amp;lng=en&amp;npl=false', 'ABC_EP25187001_en')">
      European search report
    </a>
  </td>
</tr>
"""
    row = BeautifulSoup(html, "lxml").find("tr")
    href = RegisterScraper._extract_best_href(row)
    assert href == "application?documentId=ABC&number=EP25187001&lng=en&npl=false"
    assert RegisterScraper._extract_row_document_id(row) == "ABC"


def test_contains_documents_table_for_doclist_page_shape() -> None:
    html = """
<html>
  <table class="application docList">
    <thead>
      <tr><th>Date</th><th>Document type</th><th>Procedure</th><th>Number of pages</th></tr>
    </thead>
    <tbody>
      <tr>
        <td>12.01.2026</td>
        <td><a href="application?documentId=ABC&number=EP25187001&lng=en">European search report</a></td>
        <td>Search / examination</td>
        <td>2</td>
      </tr>
    </tbody>
  </table>
</html>
"""
    assert RegisterScraper._contains_documents_table(html)


def test_extract_zip_archive_payload_from_doclist_page() -> None:
    html = """
<html>
  <form name="zipForm" action="download" method="post">
    <input type="hidden" name="number" value="EP25187001" />
    <input type="hidden" name="unip" value="false" />
    <input type="hidden" name="output" value="zip" />
  </form>
  <table>
    <tr><td><input type="checkbox" name="identivier" value="ABC123" /></td></tr>
    <tr><td><input type="checkbox" name="identivier" value="DEF456" /></td></tr>
  </table>
</html>
"""
    payload = RegisterScraper._extract_zip_archive_payload(
        html,
        "https://register.epo.org/application?tab=doclist&number=EP25187001&lng=en",
    )
    assert payload is not None
    assert payload.action_url == "https://register.epo.org/download"
    assert payload.application_number == "EP25187001"
    assert payload.document_ids == ["ABC123", "DEF456"]


def test_extract_zip_archive_payload_accepts_identifier_variant() -> None:
    html = """
<html>
  <form name="zipForm" action="/download" method="post">
    <input type="hidden" name="number" value="EP14192658" />
  </form>
  <table>
    <tr><td><input type="checkbox" name="identifier" value="DOC001" /></td></tr>
    <tr><td><input type="checkbox" name="identifier" value="DOC002" /></td></tr>
  </table>
</html>
"""
    payload = RegisterScraper._extract_zip_archive_payload(
        html,
        "https://register.epo.org/application?tab=doclist&number=EP14192658&lng=en",
    )
    assert payload is not None
    assert payload.action_url == "https://register.epo.org/download"
    assert payload.document_ids == ["DOC001", "DOC002"]


def test_extract_zip_archive_payload_keeps_hidden_fields_from_id_form() -> None:
    html = """
<html>
  <form id="zipForm" action="/download" method="post">
    <input type="hidden" name="number" value="EP17893014" />
    <input type="hidden" name="output" value="zip" />
    <input type="hidden" name="csrfToken" value="token-123" />
  </form>
  <table>
    <tr><td><input type="checkbox" name="identivier" value="ZIP001" /></td></tr>
  </table>
</html>
"""
    payload = RegisterScraper._extract_zip_archive_payload(
        html,
        "https://register.epo.org/application?tab=doclist&number=EP17893014&lng=en",
    )
    assert payload is not None
    assert payload.application_number == "EP17893014"
    assert payload.document_ids == ["ZIP001"]
    assert payload.form_data["csrfToken"] == "token-123"
    assert payload.referer_url == "https://register.epo.org/application?tab=doclist&number=EP17893014&lng=en"


def test_extract_best_href_from_onclick_document_link() -> None:
    html = """
<tr>
  <td>
    <a onclick="openDoc('application?documentId=XYZ999&amp;number=EP14192658&amp;lng=en'); return false;">
      Description
    </a>
  </td>
</tr>
"""
    row = BeautifulSoup(html, "lxml").find("tr")
    href = RegisterScraper._extract_best_href(row)
    assert href == "application?documentId=XYZ999&number=EP14192658&lng=en"
