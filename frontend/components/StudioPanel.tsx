"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ArtifactStatusResponse,
  createArtifact,
  getArtifactDownloadUrl,
  getArtifactStatus,
  listSources,
} from "../lib/api";
import {
  ARTIFACT_TASKS_STORAGE_KEY,
  CASE_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
} from "../lib/workspace";

type ArtifactTask = {
  artifact_id: string;
  artifact_type: string;
  status: string;
  output_uri?: string | null;
};

const ARTIFACT_TYPES = [
  { value: "quick_outline", label: "快速大纲" },
  { value: "timeline", label: "时间线" },
  { value: "claim_diff", label: "权利要求差异" },
  { value: "risk_report", label: "风险报告" },
];

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function parseSourceIds(input: string): string[] {
  return input
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeArtifactStatus(
  current: ArtifactTask,
  statusPayload: ArtifactStatusResponse
): ArtifactTask {
  return {
    artifact_id: current.artifact_id,
    artifact_type: typeof statusPayload.type === "string" ? statusPayload.type : current.artifact_type,
    status: statusPayload.status || current.status,
    output_uri: statusPayload.output_uri ?? current.output_uri,
  };
}

export default function StudioPanel() {
  const [token, setToken] = useState("");
  const [caseId, setCaseId] = useState("");
  const [sourceIdsInput, setSourceIdsInput] = useState("");
  const [artifactType, setArtifactType] = useState("quick_outline");
  const [paramsInput, setParamsInput] = useState("");
  const [artifacts, setArtifacts] = useState<ArtifactTask[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRefreshingAll, setIsRefreshingAll] = useState(false);
  const [refreshingId, setRefreshingId] = useState("");
  const [openingId, setOpeningId] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    const savedCaseId = localStorage.getItem(CASE_STORAGE_KEY) || "";
    const savedSourceIds = localStorage.getItem(INCLUDED_SOURCE_IDS_STORAGE_KEY) || "[]";
    const savedArtifacts = localStorage.getItem(ARTIFACT_TASKS_STORAGE_KEY) || "[]";

    setToken(savedToken);
    setCaseId(savedCaseId);

    let parsedIds: string[] = [];
    try {
      const ids = JSON.parse(savedSourceIds);
      if (Array.isArray(ids)) {
        parsedIds = ids.filter((item): item is string => typeof item === "string");
      }
    } catch {
      parsedIds = [];
    }
    setSourceIdsInput(parsedIds.join(", "));

    try {
      const tasks = JSON.parse(savedArtifacts);
      if (Array.isArray(tasks)) setArtifacts(tasks as ArtifactTask[]);
    } catch {
      setArtifacts([]);
    }

    const savedJurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
    let active = true;
    if (savedToken.trim() && savedJurisdictionCaseId.trim() && parsedIds.length > 0) {
      void (async () => {
        try {
          const sources = await listSources(savedToken.trim(), savedJurisdictionCaseId.trim());
          const validIds = new Set(sources.map((item) => item.id));
          const sanitizedIds = parsedIds.filter((id) => validIds.has(id));
          if (!active || sanitizedIds.length === parsedIds.length) return;
          setSourceIdsInput(sanitizedIds.join(", "));
          localStorage.setItem(INCLUDED_SOURCE_IDS_STORAGE_KEY, JSON.stringify(sanitizedIds));
        } catch {
          // Keep local value if network/auth is unavailable.
        }
      })();
    }

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(CASE_STORAGE_KEY, caseId);
  }, [caseId]);

  useEffect(() => {
    localStorage.setItem(ARTIFACT_TASKS_STORAGE_KEY, JSON.stringify(artifacts));
  }, [artifacts]);

  const parsedSourceIds = useMemo(() => parseSourceIds(sourceIdsInput), [sourceIdsInput]);

  const syncSourceIdsFromLocal = async () => {
    const savedSourceIds = localStorage.getItem(INCLUDED_SOURCE_IDS_STORAGE_KEY) || "[]";
    try {
      const ids = JSON.parse(savedSourceIds);
      if (!Array.isArray(ids)) {
        setErrorMessage("本地存储中的来源编号无效。");
        return;
      }

      const parsedIds = ids.filter((item): item is string => typeof item === "string");
      let nextIds = parsedIds;
      const jurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
      if (token.trim() && jurisdictionCaseId.trim() && parsedIds.length > 0) {
        try {
          const sources = await listSources(token.trim(), jurisdictionCaseId.trim());
          const validIds = new Set(sources.map((item) => item.id));
          nextIds = parsedIds.filter((id) => validIds.has(id));
          localStorage.setItem(INCLUDED_SOURCE_IDS_STORAGE_KEY, JSON.stringify(nextIds));
        } catch {
          // Ignore sync failure and keep local IDs.
        }
      }

      setSourceIdsInput(nextIds.join(", "));
      setErrorMessage("");
      setSuccessMessage(`已从本地加载 ${nextIds.length} 个来源编号。`);
    } catch {
      setErrorMessage("读取本地来源编号失败。");
    }
  };

  const generateArtifact = async () => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!caseId.trim()) {
      setErrorMessage("请输入案件编号。");
      return;
    }

    let parsedParams: Record<string, unknown> | undefined;
    if (paramsInput.trim()) {
      try {
        const params = JSON.parse(paramsInput);
        if (typeof params === "object" && params !== null && !Array.isArray(params)) {
          parsedParams = params as Record<string, unknown>;
        } else {
          setErrorMessage("参数 JSON 必须是对象。");
          return;
        }
      } catch {
        setErrorMessage("参数必须是合法 JSON。");
        return;
      }
    }

    setIsGenerating(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const response = await createArtifact(
        {
          case_id: caseId.trim(),
          artifact_type: artifactType,
          source_ids: parsedSourceIds.length > 0 ? parsedSourceIds : undefined,
          params: parsedParams,
        },
        token.trim()
      );

      const nextTask: ArtifactTask = {
        artifact_id: response.artifact_id,
        artifact_type: artifactType,
        status: response.status,
        output_uri: response.output_uri,
      };

      setArtifacts((prev) => [nextTask, ...prev]);
      const hint = response.missing_reason ? `（${response.missing_reason}）` : "";
      setSuccessMessage(`已创建产物任务：${response.artifact_id}${hint}`);
    } catch (error) {
      setErrorMessage(toMessage(error, "创建产物任务失败。"));
    } finally {
      setIsGenerating(false);
    }
  };

  const refreshArtifact = async (artifactId: string) => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    setRefreshingId(artifactId);
    setErrorMessage("");
    try {
      const payload = await getArtifactStatus(artifactId, token.trim());
      setArtifacts((prev) =>
        prev.map((item) =>
          item.artifact_id === artifactId ? normalizeArtifactStatus(item, payload) : item
        )
      );
    } catch (error) {
      setErrorMessage(toMessage(error, "刷新产物状态失败。"));
    } finally {
      setRefreshingId("");
    }
  };

  const refreshAllArtifacts = async () => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (artifacts.length === 0) {
      setSuccessMessage("当前没有可刷新的产物任务。");
      return;
    }

    setIsRefreshingAll(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const results = await Promise.all(
        artifacts.map(async (task) => ({
          id: task.artifact_id,
          payload: await getArtifactStatus(task.artifact_id, token.trim()),
        }))
      );
      setArtifacts((prev) =>
        prev.map((item) => {
          const matched = results.find((entry) => entry.id === item.artifact_id);
          return matched ? normalizeArtifactStatus(item, matched.payload) : item;
        })
      );
      setSuccessMessage("已刷新全部产物状态。");
    } catch (error) {
      setErrorMessage(toMessage(error, "刷新全部产物状态失败。"));
    } finally {
      setIsRefreshingAll(false);
    }
  };

  const openOrDownloadArtifact = async (artifactId: string) => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    setOpeningId(artifactId);
    setErrorMessage("");
    try {
      const response = await getArtifactDownloadUrl(artifactId, token.trim());
      const popup = window.open(response.url, "_blank", "noopener,noreferrer");
      if (!popup) {
        window.location.href = response.url;
      }
      setSuccessMessage(`已打开下载链接（${response.expires_in} 秒后过期）。`);
    } catch (error) {
      setErrorMessage(toMessage(error, "打开下载链接失败。"));
    } finally {
      setOpeningId("");
    }
  };

  return (
    <section className="panel">
      <h2>报告工坊</h2>
      <div className="source-controls">
        <label className="field-group">
          <span>案件编号</span>
          <input
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
            placeholder="专利案件唯一标识"
          />
        </label>
        <label className="field-group">
          <span>来源编号列表</span>
          <input
            value={sourceIdsInput}
            onChange={(event) => setSourceIdsInput(event.target.value)}
            placeholder="多个来源编号，用逗号分隔"
          />
        </label>
        <label className="field-group">
          <span>产物类型</span>
          <select value={artifactType} onChange={(event) => setArtifactType(event.target.value)}>
            {ARTIFACT_TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-group">
          <span>参数对象（可选）</span>
          <textarea
            value={paramsInput}
            onChange={(event) => setParamsInput(event.target.value)}
            placeholder='{"受众":"内部"}'
            rows={3}
          />
        </label>
        <div className="inline-actions">
          <button type="button" onClick={() => void syncSourceIdsFromLocal()}>
            使用本地已勾选来源
          </button>
          <button type="button" onClick={() => void generateArtifact()} disabled={isGenerating}>
            {isGenerating ? "生成中..." : "生成"}
          </button>
        </div>
        <div className="inline-actions">
          <button type="button" onClick={() => void refreshAllArtifacts()} disabled={isRefreshingAll}>
            {isRefreshingAll ? "刷新中..." : "全部刷新"}
          </button>
        </div>
      </div>

      {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel-message success">{successMessage}</p> : null}

      <div className="list">
        {artifacts.length === 0 ? <p className="panel-message info">暂无产物任务。</p> : null}
        {artifacts.map((task) => (
          <div className="artifact" key={task.artifact_id}>
            <div className="artifact-info">
              <strong>{task.artifact_type}</strong>
              <div className="source-meta">{task.status}</div>
              <div className="source-meta">{task.artifact_id}</div>
              {task.output_uri ? <div className="source-meta">{task.output_uri}</div> : null}
            </div>
            <div className="artifact-actions">
              <button
                type="button"
                onClick={() => void refreshArtifact(task.artifact_id)}
                disabled={refreshingId === task.artifact_id}
              >
                {refreshingId === task.artifact_id ? "刷新中..." : "刷新"}
              </button>
              <button
                type="button"
                onClick={() => void openOrDownloadArtifact(task.artifact_id)}
                disabled={task.status !== "ready" || openingId === task.artifact_id}
              >
                {openingId === task.artifact_id ? "打开中..." : "打开/下载"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
