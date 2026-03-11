# Patent Prosecution Notebook

Enterprise-ready system to ingest, analyze, and summarize patent prosecution histories with traceable citations.

## Quick start (local dev)
1) Copy `.env.example` to `.env` and update values as needed.
2) Start services:

```bash
docker compose up --build
```

3) Backend runs at http://localhost:8000
4) Frontend runs at http://localhost:3000

## Repo structure
- `backend/`: FastAPI app + Celery workers + pipelines
- `frontend/`: Next.js UI (Sources/Chat/Studio)
- `docs/`: specs, architecture, evaluation
- `infra/`: compose/helm placeholders

## Notes
- All AI outputs must include citations (source_id, chunk_id, page, quote).
- Ingestion is plugin-based; manual upload is always available.
