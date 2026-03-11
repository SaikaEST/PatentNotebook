# Architecture Notes

## Core principles
- All AI outputs must include citations; if missing, set missing=true and explain why.
- Ingestion is plugin-based; manual upload is always available.
- Async tasks for ingest/parse/embed/extract/artifact/export.

## Services
- API: FastAPI + SQLAlchemy
- Worker: Celery
- Storage: MinIO
- Database: PostgreSQL + pgvector
- Cache/Queue: Redis

## Multi-tenant model
- Tenant -> Workspace -> Project -> Case
- RBAC enforced at API layer (org_admin, workspace_admin, ipr_editor, viewer)

## Observability
- Structured logs, metrics, tracing (OpenTelemetry-ready)
