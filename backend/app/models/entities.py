import uuid
from sqlalchemy import Column, String, DateTime, Integer, Boolean, ForeignKey, Text, Float, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    roles_json = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PatentFamily(Base):
    __tablename__ = "patent_families"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    family_no = Column(String(255), nullable=True)
    members_json = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PatentCase(Base):
    __tablename__ = "patent_cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    family_id = Column(UUID(as_uuid=True), ForeignKey("patent_families.id"), nullable=True)
    title = Column(String(512), nullable=True)
    status = Column(String(64), default="active")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class JurisdictionCase(Base):
    __tablename__ = "jurisdiction_cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("patent_cases.id"), nullable=False)
    jurisdiction = Column(String(32), nullable=False)
    application_no = Column(String(128), nullable=True)
    publication_no = Column(String(128), nullable=True)
    filing_date = Column(DateTime, nullable=True)
    grant_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SourceDocument(Base):
    __tablename__ = "source_documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_case_id = Column(UUID(as_uuid=True), ForeignKey("jurisdiction_cases.id"), nullable=False)
    doc_type = Column(String(64), nullable=False)
    language = Column(String(16), nullable=True)
    source_type = Column(String(32), default="upload")
    file_uri = Column(String(1024), nullable=True)
    text_uri = Column(String(1024), nullable=True)
    meta_json = Column(JSON, default=dict)
    version = Column(String(64), nullable=True)
    included = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("source_documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_no = Column(Integer, nullable=True)
    offset_start = Column(Integer, nullable=True)
    offset_end = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_case_id = Column(UUID(as_uuid=True), ForeignKey("jurisdiction_cases.id"), nullable=False)
    date = Column(DateTime, nullable=True)
    doc_type = Column(String(64), nullable=False)
    links_json = Column(JSON, default=dict)
    claims_version_id = Column(UUID(as_uuid=True), ForeignKey("claim_set_versions.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class OfficeActionIssue(Base):
    __tablename__ = "office_action_issues"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), nullable=False)
    issue_type = Column(String(64), nullable=False)
    legal_basis = Column(String(128), nullable=True)
    claims_json = Column(JSON, default=list)
    references_json = Column(JSON, default=list)
    status = Column(String(32), default="open")
    created_at = Column(DateTime, server_default=func.now())


class ApplicantResponseArgument(Base):
    __tablename__ = "applicant_response_arguments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issue_id = Column(UUID(as_uuid=True), ForeignKey("office_action_issues.id"), nullable=False)
    argument_text = Column(Text, nullable=False)
    evidence_json = Column(JSON, default=list)
    amendment_refs_json = Column(JSON, default=list)
    created_at = Column(DateTime, server_default=func.now())


class ClaimSetVersion(Base):
    __tablename__ = "claim_set_versions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_case_id = Column(UUID(as_uuid=True), ForeignKey("jurisdiction_cases.id"), nullable=False)
    version_no = Column(String(64), nullable=False)
    date = Column(DateTime, nullable=True)
    claims_text_uri = Column(String(1024), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ClaimDiff(Base):
    __tablename__ = "claim_diffs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_version_id = Column(UUID(as_uuid=True), ForeignKey("claim_set_versions.id"), nullable=False)
    to_version_id = Column(UUID(as_uuid=True), ForeignKey("claim_set_versions.id"), nullable=False)
    claim_no = Column(String(64), nullable=False)
    change_type = Column(String(32), nullable=False)
    feature_diff_json = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())


class PriorArtReference(Base):
    __tablename__ = "prior_art_references"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_case_id = Column(UUID(as_uuid=True), ForeignKey("jurisdiction_cases.id"), nullable=False)
    ref_no = Column(String(64), nullable=True)
    ref_type = Column(String(32), nullable=True)
    title = Column(String(512), nullable=True)
    cited_count = Column(Integer, default=0)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class RiskSignal(Base):
    __tablename__ = "risk_signals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jurisdiction_case_id = Column(UUID(as_uuid=True), ForeignKey("jurisdiction_cases.id"), nullable=False)
    risk_type = Column(String(64), nullable=False)
    score = Column(Float, nullable=True)
    evidence_json = Column(JSON, default=list)
    suggestion = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("patent_cases.id"), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    model = Column(String(128), nullable=True)
    config_json = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())


class Note(Base):
    __tablename__ = "notes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    content = Column(Text, nullable=False)
    locked = Column(Boolean, default=False)
    source_ref_id = Column(UUID(as_uuid=True), ForeignKey("source_documents.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("patent_cases.id"), nullable=False)
    type = Column(String(64), nullable=False)
    status = Column(String(32), default="queued")
    output_uri = Column(String(1024), nullable=True)
    meta_json = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(128), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(64), nullable=True)
    meta_json = Column(JSON, default=dict)
    created_at = Column(DateTime, server_default=func.now())
