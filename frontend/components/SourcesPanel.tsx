"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import {
  createCase,
  getIngestTaskStatus,
  IngestTaskStatusResponse,
  listSources,
  SourceDocument,
  startIngest,
  updateSourceIncluded,
  uploadSource,
} from "../lib/api";
import {
  CASE_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
} from "../lib/workspace";

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function inferCaseNumberType(value: string): "application_no" | "publication_no" {
  const normalized = value.toUpperCase().replace(/\s+/g, "");
  if (
    normalized.includes(".") ||
    /^EP?\d{8}\.\d$/.test(normalized) ||
    /^EP?\d{8}$/.test(normalized)
  ) {
    return "application_no";
  }
  return "publication_no";
}

function toDocTypeCode(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "office action") return "office_action";
  if (normalized === "response") return "response";
  return value.trim();
}

function toLanguageCode(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "chinese" || normalized === "zh") return "ZH";
  if (normalized === "english" || normalized === "en") return "EN";
  return value.trim();
}

export default function SourcesPanel() {
  const [token, setToken] = useState("");
  const [caseId, setCaseId] = useState("");
  const [jurisdictionCaseId, setJurisdictionCaseId] = useState("");
  const [caseTitle, setCaseTitle] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [docType, setDocType] = useState("office action");
  const [language, setLanguage] = useState("EN");
  const [version, setVersion] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCreatingCase, setIsCreatingCase] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [ingestTask, setIngestTask] = useState<IngestTaskStatusResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    const savedCaseId = localStorage.getItem(CASE_STORAGE_KEY) || "";
    const savedJurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";

    setToken(savedToken);
    setCaseId(savedCaseId);
    setJurisdictionCaseId(savedJurisdictionCaseId);
    setCaseNumber(savedJurisdictionCaseId);
  }, []);

  useEffect(() => {
    localStorage.setItem(CASE_STORAGE_KEY, caseId);
  }, [caseId]);

  useEffect(() => {
    localStorage.setItem(JURISDICTION_CASE_STORAGE_KEY, jurisdictionCaseId);
  }, [jurisdictionCaseId]);

  const persistIncludedSourceIds = (items: SourceDocument[]) => {
    const includedIds = items.filter((item) => item.included).map((item) => item.id);
    localStorage.setItem(INCLUDED_SOURCE_IDS_STORAGE_KEY, JSON.stringify(includedIds));
  };

  const refreshSources = async (preserveMessages = false) => {
    if (!token.trim()) {
      setErrorMessage("Please log in first.");
      return;
    }
    setIsLoading(true);
    if (!preserveMessages) {
      setErrorMessage("");
      setSuccessMessage("");
    }
    try {
      const data = await listSources(token.trim(), jurisdictionCaseId.trim() || undefined);
      setSources(data);
      persistIncludedSourceIds(data);
    } catch (error) {
      setErrorMessage(toMessage(error, "Failed to load sources."));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (!token.trim() || !ingestTask?.task_id) return;
    if (ingestTask.state === "SUCCESS" || ingestTask.state === "FAILURE") return;

    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await getIngestTaskStatus(ingestTask.task_id, token.trim());
        if (cancelled) return;
        setIngestTask(next);
        if (next.state === "SUCCESS") {
          setIsIngesting(false);
          await refreshSources(true);
          setSuccessMessage(`Ingest completed. Created ${next.created_sources} sources.`);
          window.clearInterval(timer);
        } else if (next.state === "FAILURE") {
          setIsIngesting(false);
          setErrorMessage(next.message || "Ingest failed.");
          window.clearInterval(timer);
        }
      } catch (error) {
        if (cancelled) return;
        setIsIngesting(false);
        setErrorMessage(toMessage(error, "Failed to load ingest progress."));
        window.clearInterval(timer);
      }
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [ingestTask?.task_id, ingestTask?.state, token]);

  const createEuCaseAndSaveIds = async () => {
    if (!token.trim()) {
      setErrorMessage("Please log in first.");
      return;
    }
    if (!caseNumber.trim()) {
      setErrorMessage("Enter an EP publication or application number.");
      return;
    }

    const numberType = inferCaseNumberType(caseNumber.trim());
    const payload =
      numberType === "application_no"
        ? {
            title: caseTitle.trim() || `EU ${caseNumber.trim()}`,
            jurisdiction: "EU",
            application_no: caseNumber.trim(),
          }
        : {
            title: caseTitle.trim() || `EU ${caseNumber.trim()}`,
            jurisdiction: "EU",
            publication_no: caseNumber.trim(),
          };

    setIsCreatingCase(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const result = await createCase(payload, token.trim());
      setCaseId(result.id);
      setJurisdictionCaseId(
        result.jurisdiction_case_id || result.application_no || result.publication_no || caseNumber.trim()
      );
      setSuccessMessage(`Case created: ${result.id}`);
    } catch (error) {
      setErrorMessage(toMessage(error, "Failed to create case."));
    } finally {
      setIsCreatingCase(false);
    }
  };

  const startEpoIngestAndRefresh = async () => {
    if (!token.trim()) {
      setErrorMessage("Please log in first.");
      return;
    }
    if (!caseId.trim()) {
      setErrorMessage("Enter a case id first.");
      return;
    }

    setIsIngesting(true);
    setErrorMessage("");
    setSuccessMessage("");
    setIngestTask(null);
    try {
      const result = await startIngest(
        caseId.trim(),
        {
          providers: ["epo"],
          prefer_official: true,
          include_dms_fallback: false,
          trigger_processing: true,
        },
        token.trim()
      );
      setSuccessMessage(`Ingest task queued: ${result.task_id}`);
      setIngestTask({
        task_id: result.task_id,
        state: "PENDING",
        status: "queued",
        stage: "queued",
        message: "Queued",
        current: 0,
        total: 0,
        percent: 0,
        case_id: result.case_id,
        created_sources: 0,
        missing: result.missing,
        missing_reason: result.missing_reason,
        followup_suggestions: result.followup_suggestions || [],
      });
    } catch (error) {
      setIsIngesting(false);
      setErrorMessage(toMessage(error, "Failed to start EPO ingest."));
    }
  };

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token.trim()) {
      setErrorMessage("Please log in first.");
      return;
    }
    if (!jurisdictionCaseId.trim()) {
      setErrorMessage("Enter a jurisdiction case id first.");
      return;
    }
    if (!docType.trim()) {
      setErrorMessage("Enter a document type.");
      return;
    }
    if (!selectedFile) {
      setErrorMessage("Select a file first.");
      return;
    }

    setIsUploading(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      await uploadSource({
        token: token.trim(),
        jurisdictionCaseId: jurisdictionCaseId.trim(),
        docType: toDocTypeCode(docType),
        language: language.trim() ? toLanguageCode(language) : undefined,
        version: version.trim() || undefined,
        file: selectedFile,
      });
      setSuccessMessage("Upload completed. Parsing has started.");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refreshSources(true);
    } catch (error) {
      setErrorMessage(toMessage(error, "Upload failed."));
    } finally {
      setIsUploading(false);
    }
  };

  const toggleIncluded = async (source: SourceDocument) => {
    if (!token.trim()) {
      setErrorMessage("Please log in first.");
      return;
    }
    const nextIncluded = !source.included;
    const nextSources = sources.map((item) =>
      item.id === source.id ? { ...item, included: nextIncluded } : item
    );
    setSources(nextSources);
    persistIncludedSourceIds(nextSources);

    try {
      await updateSourceIncluded(token.trim(), source.id, nextIncluded);
    } catch (error) {
      const rollbackSources = sources.map((item) =>
        item.id === source.id ? { ...item, included: source.included } : item
      );
      setSources(rollbackSources);
      persistIncludedSourceIds(rollbackSources);
      setErrorMessage(toMessage(error, "Failed to update source inclusion."));
    }
  };

  return (
    <section className="panel">
      <h2>Sources</h2>
      <div className="source-controls">
        <label className="field-group">
          <span>Case ID</span>
          <input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="Internal case id" />
        </label>
        <label className="field-group">
          <span>EP Number</span>
          <input
            value={caseNumber}
            onChange={(e) => setCaseNumber(e.target.value)}
            placeholder="EP publication or application number"
          />
        </label>
        <label className="field-group">
          <span>Case Title</span>
          <input value={caseTitle} onChange={(e) => setCaseTitle(e.target.value)} placeholder="Optional title" />
        </label>
        <label className="field-group">
          <span>Jurisdiction Case ID</span>
          <input
            value={jurisdictionCaseId}
            onChange={(e) => setJurisdictionCaseId(e.target.value)}
            placeholder="Jurisdiction case id"
          />
        </label>
        <div className="inline-actions">
          <button type="button" onClick={() => void createEuCaseAndSaveIds()} disabled={isCreatingCase}>
            {isCreatingCase ? "Creating..." : "Create EU Case"}
          </button>
          <button type="button" onClick={() => void startEpoIngestAndRefresh()} disabled={isIngesting}>
            {isIngesting ? "Running..." : "Start EPO Ingest"}
          </button>
        </div>
        <div className="inline-actions">
          <button type="button" onClick={() => void refreshSources()} disabled={isLoading}>
            {isLoading ? "Refreshing..." : "Refresh Sources"}
          </button>
        </div>
      </div>

      <form className="source-controls" onSubmit={handleUpload}>
        <label className="field-group">
          <span>Document Type</span>
          <input value={docType} onChange={(e) => setDocType(e.target.value)} placeholder="office action" />
        </label>
        <label className="field-group">
          <span>Language</span>
          <input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="EN" />
        </label>
        <label className="field-group">
          <span>Version</span>
          <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="Optional version" />
        </label>
        <label className="field-group">
          <span>File</span>
          <input ref={fileInputRef} type="file" onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
        </label>
        <div className="inline-actions">
          <button type="submit" disabled={isUploading}>
            {isUploading ? "Uploading..." : "Upload"}
          </button>
        </div>
      </form>

      {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel-message success">{successMessage}</p> : null}
      {ingestTask ? (
        <div className="task-progress-card">
          <div className="task-progress-header">
            <strong>Ingest Progress</strong>
            <span>{ingestTask.percent}%</span>
          </div>
          <div className="task-progress-track">
            <div className="task-progress-fill" style={{ width: `${ingestTask.percent}%` }} />
          </div>
          <div className="source-meta">
            <span>{ingestTask.stage || ingestTask.status}</span>
            <span>{ingestTask.total > 0 ? `${ingestTask.current}/${ingestTask.total}` : ingestTask.state}</span>
          </div>
          {ingestTask.message ? <p className="panel-message info">{ingestTask.message}</p> : null}
        </div>
      ) : null}

      <div className="list">
        {sources.length === 0 ? <p className="panel-message info">No source documents yet.</p> : null}
        {sources.map((src) => (
          <div key={src.id} className="source-card">
            <strong>{src.doc_type}</strong>
            <div className="source-meta">
              <span>{src.language || "-"}</span>
              <span>{src.source_type || "upload"}</span>
            </div>
            <label>
              <input type="checkbox" checked={src.included} onChange={() => void toggleIncluded(src)} />
              <span>Include in QA</span>
            </label>
          </div>
        ))}
      </div>
    </section>
  );
}
