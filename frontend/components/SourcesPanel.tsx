"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createCase,
  getIngestTaskStatus,
  IngestTaskStatusResponse,
  listSources,
  queueSourceOcr,
  queueSourceProcess,
  queueSourcesOcr,
  queueSourcesProcess,
  SourceDocument,
  startIngest,
  updateSourceIncluded,
  uploadSource,
} from "../lib/api";
import {
  CASE_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  SOURCES_FORM_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
} from "../lib/workspace";

const CATEGORY_ORDER = [
  "communication_from_examining_division",
  "annex_to_the_communication",
  "reply_to_communication_from_examining_division",
  "claims",
  "amended_claims",
  "amended_claims_with_annotations",
  "european_search_opinion",
  "other",
] as const;

type CategoryKey = (typeof CATEGORY_ORDER)[number];

type SourceGroup = {
  key: CategoryKey;
  label: string;
  items: SourceDocument[];
};

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  communication_from_examining_division: "Communication from the Examining Division",
  annex_to_the_communication: "Annex to the communication",
  reply_to_communication_from_examining_division: "Reply to communication from the Examining Division",
  claims: "Claims",
  amended_claims: "Amended claims",
  amended_claims_with_annotations: "Amended claims with annotations",
  european_search_opinion: "European search opinion",
  other: "Other",
};

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function inferCaseNumberType(value: string): "application_no" | "publication_no" {
  const normalized = value.toUpperCase().replace(/\s+/g, "");
  if (normalized.includes(".") || /^EP?\d{8}\.\d$/.test(normalized) || /^EP?\d{8}$/.test(normalized)) {
    return "application_no";
  }
  return "publication_no";
}

function toDocTypeCode(value: string): string {
  return value.trim();
}

function toLanguageCode(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "chinese" || normalized === "zh") return "ZH";
  if (normalized === "english" || normalized === "en") return "EN";
  return value.trim();
}

function normalizeCategory(docType?: string | null): CategoryKey {
  const normalized = (docType || "").trim().toLowerCase();
  if (CATEGORY_ORDER.includes(normalized as CategoryKey)) {
    return normalized as CategoryKey;
  }
  return "other";
}

function getSourceTitle(source: SourceDocument): string {
  return source.file_name?.trim() || CATEGORY_LABELS[normalizeCategory(source.doc_type)];
}

export default function SourcesPanel() {
  const [token, setToken] = useState("");
  const [caseId, setCaseId] = useState("");
  const [jurisdictionCaseId, setJurisdictionCaseId] = useState("");
  const [caseTitle, setCaseTitle] = useState("");
  const [caseNumber, setCaseNumber] = useState("");
  const [docType, setDocType] = useState("other");
  const [language, setLanguage] = useState("EN");
  const [version, setVersion] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sources, setSources] = useState<SourceDocument[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCreatingCase, setIsCreatingCase] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [isQueueingProcess, setIsQueueingProcess] = useState(false);
  const [isQueueingOcr, setIsQueueingOcr] = useState(false);
  const [sourceTaskKey, setSourceTaskKey] = useState<string | null>(null);
  const [ingestTask, setIngestTask] = useState<IngestTaskStatusResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [hasRestored, setHasRestored] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    const savedCaseId = localStorage.getItem(CASE_STORAGE_KEY) || "";
    const savedJurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
    const savedSourcesForm = localStorage.getItem(SOURCES_FORM_STORAGE_KEY) || "";

    setToken(savedToken);
    setCaseId(savedCaseId);
    setJurisdictionCaseId(savedJurisdictionCaseId);

    let restoredCaseTitle = "";
    let restoredCaseNumber = savedJurisdictionCaseId;
    let restoredDocType = "other";
    let restoredLanguage = "EN";
    let restoredVersion = "";

    try {
      const savedForm = JSON.parse(savedSourcesForm);
      if (savedForm && typeof savedForm === "object") {
        if (typeof savedForm.caseTitle === "string") restoredCaseTitle = savedForm.caseTitle;
        if (typeof savedForm.caseNumber === "string" && savedForm.caseNumber.trim()) {
          restoredCaseNumber = savedForm.caseNumber;
        }
        if (typeof savedForm.docType === "string" && savedForm.docType.trim()) {
          restoredDocType = savedForm.docType;
        }
        if (typeof savedForm.language === "string" && savedForm.language.trim()) {
          restoredLanguage = savedForm.language;
        }
        if (typeof savedForm.version === "string") restoredVersion = savedForm.version;
      }
    } catch {
      // Ignore invalid local state.
    }

    setCaseTitle(restoredCaseTitle);
    setCaseNumber(restoredCaseNumber);
    setDocType(restoredDocType);
    setLanguage(restoredLanguage);
    setVersion(restoredVersion);
    setHasRestored(true);
  }, []);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(CASE_STORAGE_KEY, caseId);
  }, [caseId, hasRestored]);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(JURISDICTION_CASE_STORAGE_KEY, jurisdictionCaseId);
  }, [jurisdictionCaseId, hasRestored]);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(
      SOURCES_FORM_STORAGE_KEY,
      JSON.stringify({
        caseTitle,
        caseNumber,
        docType,
        language,
        version,
      })
    );
  }, [caseNumber, caseTitle, docType, hasRestored, language, version]);

  const sourceGroups = useMemo<SourceGroup[]>(() => {
    const grouped = new Map<CategoryKey, SourceDocument[]>();
    for (const key of CATEGORY_ORDER) grouped.set(key, []);
    for (const source of sources) {
      const key = normalizeCategory(source.doc_type);
      grouped.get(key)?.push(source);
    }
    return CATEGORY_ORDER.map((key) => ({
      key,
      label: CATEGORY_LABELS[key],
      items: grouped.get(key) || [],
    })).filter((group) => group.items.length > 0);
  }, [sources]);

  const persistIncludedSourceIds = (items: SourceDocument[]) => {
    const includedIds = items.filter((item) => item.included).map((item) => item.id);
    localStorage.setItem(INCLUDED_SOURCE_IDS_STORAGE_KEY, JSON.stringify(includedIds));
  };

  useEffect(() => {
    if (!token.trim() || !jurisdictionCaseId.trim()) return;
    void refreshSources(true);
  }, [token, jurisdictionCaseId]);

  const refreshSources = async (preserveMessages = false) => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
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
      setExpandedGroups((current) => {
        const next = { ...current };
        for (const source of data) {
          const key = normalizeCategory(source.doc_type);
          if (!(key in next)) next[key] = false;
        }
        return next;
      });
    } catch (error) {
      setErrorMessage(toMessage(error, "加载来源文档失败。"));
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
          setSuccessMessage(`抓取完成，已创建 ${next.created_sources} 份来源文档。`);
          window.clearInterval(timer);
        } else if (next.state === "FAILURE") {
          setIsIngesting(false);
          setErrorMessage(next.message || "抓取失败。");
          window.clearInterval(timer);
        }
      } catch (error) {
        if (cancelled) return;
        setIsIngesting(false);
        setErrorMessage(toMessage(error, "加载抓取进度失败。"));
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
      setErrorMessage("请先登录。");
      return;
    }
    if (!caseNumber.trim()) {
      setErrorMessage("请输入 EP 公开编号或申请号。");
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
      setSuccessMessage(`案件已创建：${result.id}`);
    } catch (error) {
      setErrorMessage(toMessage(error, "创建案件失败。"));
    } finally {
      setIsCreatingCase(false);
    }
  };

  const startEpoIngestAndRefresh = async () => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!caseId.trim()) {
      setErrorMessage("请先输入案件 ID。");
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

      setSuccessMessage(`已提交抓取任务：${result.task_id}`);
      setIngestTask({
        task_id: result.task_id,
        state: "PENDING",
        status: "queued",
        stage: "queued",
        message: "已排队。",
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
      setErrorMessage(toMessage(error, "启动 EPO 抓取失败。"));
    }
  };

  const queueCurrentCaseTask = async (mode: "process" | "ocr") => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!jurisdictionCaseId.trim()) {
      setErrorMessage("请先输入司法辖区案件 ID。");
      return;
    }

    const setLoading = mode === "ocr" ? setIsQueueingOcr : setIsQueueingProcess;
    setLoading(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const response =
        mode === "ocr"
          ? await queueSourcesOcr(token.trim(), {
              jurisdictionCaseId: jurisdictionCaseId.trim(),
              includedOnly: true,
            })
          : await queueSourcesProcess(token.trim(), {
              jurisdictionCaseId: jurisdictionCaseId.trim(),
              includedOnly: true,
            });
      await refreshSources(true);
      setSuccessMessage(
        `${mode === "ocr" ? "OCR" : "解析"}任务已提交，包含 ${response.queued_count} 份已勾选文档。`
      );
    } catch (error) {
      setErrorMessage(toMessage(error, mode === "ocr" ? "提交 OCR 任务失败。" : "提交解析任务失败。"));
    } finally {
      setLoading(false);
    }
  };

  const queueSingleSourceTask = async (source: SourceDocument, mode: "process" | "ocr") => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }

    const taskKey = `${mode}:${source.id}`;
    setSourceTaskKey(taskKey);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      if (mode === "ocr") {
        await queueSourceOcr(token.trim(), source.id);
      } else {
        await queueSourceProcess(token.trim(), source.id);
      }
      await refreshSources(true);
      setSuccessMessage(`${mode === "ocr" ? "OCR" : "解析"}任务已提交：${getSourceTitle(source)}`);
    } catch (error) {
      setErrorMessage(toMessage(error, mode === "ocr" ? "提交单文档 OCR 失败。" : "提交单文档解析失败。"));
    } finally {
      setSourceTaskKey(null);
    }
  };

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!jurisdictionCaseId.trim()) {
      setErrorMessage("请先输入司法辖区案件 ID。");
      return;
    }
    if (!docType.trim()) {
      setErrorMessage("请输入文档类型。");
      return;
    }
    if (!selectedFile) {
      setErrorMessage("请先选择文件。");
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
      setSuccessMessage("上传完成，已开始解析。");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refreshSources(true);
    } catch (error) {
      setErrorMessage(toMessage(error, "上传失败。"));
    } finally {
      setIsUploading(false);
    }
  };

  const toggleIncluded = async (source: SourceDocument) => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
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
      setErrorMessage(toMessage(error, "更新文档勾选状态失败。"));
    }
  };

  const toggleGroup = (groupKey: CategoryKey) => {
    setExpandedGroups((current) => ({
      ...current,
      [groupKey]: !current[groupKey],
    }));
  };

  return (
    <section className="panel">
      <h2>来源文档</h2>
      <div className="source-controls">
        <label className="field-group">
          <span>案件 ID</span>
          <input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="内部案件 ID" />
        </label>
        <label className="field-group">
          <span>EP 编号</span>
          <input
            value={caseNumber}
            onChange={(e) => setCaseNumber(e.target.value)}
            placeholder="EP 公开编号或申请号"
          />
        </label>
        <label className="field-group">
          <span>案件标题</span>
          <input value={caseTitle} onChange={(e) => setCaseTitle(e.target.value)} placeholder="可选标题" />
        </label>
        <label className="field-group">
          <span>司法辖区案件 ID</span>
          <input
            value={jurisdictionCaseId}
            onChange={(e) => setJurisdictionCaseId(e.target.value)}
            placeholder="司法辖区案件 ID"
          />
        </label>
        <div className="inline-actions">
          <button type="button" onClick={() => void createEuCaseAndSaveIds()} disabled={isCreatingCase}>
            {isCreatingCase ? "创建中..." : "创建 EU 案件"}
          </button>
          <button type="button" onClick={() => void startEpoIngestAndRefresh()} disabled={isIngesting}>
            {isIngesting ? "运行中..." : "开始 EPO 抓取"}
          </button>
        </div>
        <div className="inline-actions">
          <button type="button" onClick={() => void queueCurrentCaseTask("process")} disabled={isQueueingProcess}>
            {isQueueingProcess ? "提交中..." : "解析已勾选文档"}
          </button>
          <button type="button" onClick={() => void queueCurrentCaseTask("ocr")} disabled={isQueueingOcr}>
            {isQueueingOcr ? "提交中..." : "对已勾选文档执行 OCR"}
          </button>
        </div>
        <div className="inline-actions">
          <button type="button" onClick={() => void refreshSources()} disabled={isLoading}>
            {isLoading ? "刷新中..." : "刷新文档列表"}
          </button>
        </div>
      </div>

      <form className="source-controls" onSubmit={handleUpload}>
        <label className="field-group">
          <span>文档类型</span>
          <input value={docType} onChange={(e) => setDocType(e.target.value)} placeholder="other" />
        </label>
        <label className="field-group">
          <span>语言</span>
          <input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="EN" />
        </label>
        <label className="field-group">
          <span>版本</span>
          <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="可选版本" />
        </label>
        <label className="field-group">
          <span>文件</span>
          <input ref={fileInputRef} type="file" onChange={(e) => setSelectedFile(e.target.files?.[0] || null)} />
        </label>
        <div className="inline-actions">
          <button type="submit" disabled={isUploading}>
            {isUploading ? "上传中..." : "上传"}
          </button>
        </div>
      </form>

      {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel-message success">{successMessage}</p> : null}

      {ingestTask ? (
        <div className="task-progress-card">
          <div className="task-progress-header">
            <strong>抓取进度</strong>
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

      <div className="list source-group-list">
        {sourceGroups.length === 0 ? <p className="panel-message info">暂无来源文档。</p> : null}
        {sourceGroups.map((group) => {
          const expanded = Boolean(expandedGroups[group.key]);
          const visibleItems = expanded ? group.items : group.items.slice(0, 3);
          return (
            <section key={group.key} className="source-group-card">
              <button type="button" className="source-group-header" onClick={() => toggleGroup(group.key)}>
                <span>{group.label}</span>
                <span>{group.items.length} 份文档{expanded ? " 收起" : " 展开全部"}</span>
              </button>
              <div className="list">
                {visibleItems.map((src) => {
                  const isProcessingSource = sourceTaskKey === `process:${src.id}`;
                  const isOcrSource = sourceTaskKey === `ocr:${src.id}`;
                  return (
                    <div key={src.id} className="source-card">
                      <strong>{getSourceTitle(src)}</strong>
                      <div className="source-meta">
                        <span>{CATEGORY_LABELS[normalizeCategory(src.doc_type)]}</span>
                        <span>{src.language || "-"}</span>
                      </div>
                      <div className="source-meta">
                        <span>{src.source_type || "upload"}</span>
                        <span>{src.included ? "已勾选" : "未勾选"}</span>
                      </div>
                      <label>
                        <input type="checkbox" checked={src.included} onChange={() => void toggleIncluded(src)} />
                        <span>纳入问答范围</span>
                      </label>
                      <div className="inline-actions">
                        <button
                          type="button"
                          onClick={() => void queueSingleSourceTask(src, "process")}
                          disabled={Boolean(sourceTaskKey)}
                        >
                          {isProcessingSource ? "提交中..." : "解析"}
                        </button>
                        <button
                          type="button"
                          onClick={() => void queueSingleSourceTask(src, "ocr")}
                          disabled={Boolean(sourceTaskKey)}
                        >
                          {isOcrSource ? "提交中..." : "OCR"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}
