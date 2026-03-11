# EP Ingest (Module 1 + Module 2)

Enterprise-grade EP-only prosecution ingestion service implementing:

- Module 1: EP Register document acquisition
- Module 2: text extraction, rule-based classification, and timeline generation

Scope intentionally excludes CN/US and Modules 3/4.

## Requirements

- Python 3.11+

## Install

```bash
cd ep_ingest
python -m pip install -e .[dev,pdf]
```

If `PyMuPDF` is unavailable, a limited fallback PDF text extractor is used.
If your environment blocks package index access, use:

```bash
python -m pip install -e . --no-build-isolation
```

For anti-bot fallback (Cloudflare challenge pages), install Playwright:

```bash
python -m pip install playwright
python -m playwright install chromium
```

If you still get `RestrictedRequest`, that is an IP-level block by EP Register.
Run from an allowed egress IP or enterprise proxy.

## CLI

```bash
ep_ingest fetch --id EP4674798 --out ./data
ep_ingest run --id EP4674798 --out ./data
ep_ingest timeline --id EP4674798 --out ./data
```

Use official EPO OPS v3.2 API (OAuth2) for examination-related register events and
downloadable image documents:

```bash
set EPO_OPS_KEY=your_consumer_key
set EPO_OPS_SECRET=your_consumer_secret
ep_ingest fetch-ops --id EP4674798 --out ./data --download --max-files 10
```

Generated OPS artifacts:

- `./data/<patent_fs_id>/EP/ops_exam/ops_exam_files.json`
- `./data/<patent_fs_id>/EP/ops_exam/register_events.xml`
- `./data/<patent_fs_id>/EP/ops_exam/register_procedural-steps.xml`
- `./data/<patent_fs_id>/EP/ops_exam/register_biblio.xml`
- `./data/<patent_fs_id>/EP/ops_exam/files/*.pdf` (if downloadable via OPS image endpoints)

Disable browser fallback if needed:

```bash
ep_ingest run --id EP4674798 --out ./data --no-browser-fallback
```

Use enterprise proxy/allowed egress:

```bash
ep_ingest run --id EP4674798 --out ./data --proxy http://proxy-host:port
```

For Cloudflare-managed challenge pages that do not clear in headless mode, use a
persistent headed browser profile:

```bash
ep_ingest fetch --id EP17893014 --out ./data --browser-headed --browser-user-data-dir ./.ep-browser
```

`--id` accepts publication (`EP4674798`) or application (`EP25187001.0`) numbers.

## Output

Artifacts are written under:

`./data/<patent_fs_id>/EP/...`

Where `patent_fs_id` is the filesystem-safe form of `patent_id` (`EP:...` becomes `EP_...`).

Generated files:

- `documents.json`
- `timeline.json`
- `timeline.md`
- `files/<document_id>.pdf|html`
- `files/zip_archive/*` (when EP Register Zip Archive is available)
- `files/comparison_candidates/<category>/*`
- `files/comparison_candidates/manifest.json`
- `text/<document_id>.txt`

## Data Model

Each document record contains:

- `source="epo_register"`
- `register_document_id`
- `date` (ISO-8601 when parseable)
- `document_type_raw`
- `procedure`
- `pages`
- `file_url`
- `content_type` (`pdf` or `html`)
- `local_path`
- `raw_text`
- `doc_type_norm`:
  `search_report | search_opinion | examination_communication | applicant_response | amendment | grant_decision | procedural_notice | filing_document | other`

Timeline is sorted by:

1. date ascending
2. `doc_type_norm`
3. `document_type_raw`

## Architecture Notes

- `ep_ingest/http_client.py`: HTTP with rate limiting, retries, and conditional cache (ETag/Last-Modified + body hash).
- `ep_ingest/browser_bypass.py`: optional browser session bootstrap (Playwright) for anti-bot cookie acquisition.
- `ep_ingest/scraper/register.py`: EP Register case resolution, All Documents parsing, and artifact download.
- `ep_ingest/ops_client.py`: official OPS v3.2 OAuth2 + register/images endpoints client.
- `ep_ingest/ops_exam_files.py`: examination event extraction and OPS image-file retrieval flow.
- `ep_ingest/processing/extract.py`: PDF/HTML text extraction (PyMuPDF + BeautifulSoup).
- `ep_ingest/processing/classify.py`: rule-based classifier using Register labels and extracted text.
- `ep_ingest/processing/timeline.py`: timeline sort + markdown rendering.
- `ep_ingest/service.py`: orchestration and persistence.

## Observability

- Correlation IDs are attached to logs per run.
- Metrics counters tracked and persisted in `documents.json`:
  - `download_success`
  - `download_fail`
  - `parse_fail`
  - `classify_fail`

## Error Taxonomy

Typed exceptions:

- `network`
- `parsing`
- `unexpected_html`
- `blocked`
- `not_found`

## Tests

```bash
cd ep_ingest
pytest
```

Included fixtures:

- Recorded-style Register case page HTML
- Recorded-style Register all-documents HTML
- Two sample PDFs (`search_report` and `procedural_notice`)
