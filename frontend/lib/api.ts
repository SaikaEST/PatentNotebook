const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type SourceDocument = {
  id: string;
  doc_type: string;
  language?: string | null;
  source_type?: string | null;
  included: boolean;
  file_uri?: string | null;
};

export type PatentCasePayload = {
  title?: string;
  family_id?: string;
  workspace_id?: string;
  project_id?: string;
  jurisdiction?: string;
  application_no?: string;
  publication_no?: string;
  family_strategy?: string;
};

export type PatentCaseResponse = {
  id: string;
  title?: string | null;
  status: string;
  jurisdiction_case_id?: string | null;
  jurisdiction?: string | null;
  publication_no?: string | null;
  application_no?: string | null;
};

export type IngestResponse = {
  status: string;
  case_id: string;
  task_id: string;
  missing?: boolean;
  missing_reason?: string | null;
  followup_suggestions?: string[];
  task_options?: Record<string, unknown>;
};

export type IngestTaskStatusResponse = {
  task_id: string;
  state: string;
  status: string;
  stage?: string | null;
  message?: string | null;
  current: number;
  total: number;
  percent: number;
  case_id?: string | null;
  created_sources: number;
  missing?: boolean;
  missing_reason?: string | null;
  followup_suggestions?: string[];
};

export type ArtifactCreateResponse = {
  artifact_id: string;
  status: string;
  output_uri?: string | null;
  missing?: boolean;
  missing_reason?: string | null;
};

export type ArtifactStatusResponse = {
  id: string;
  status: string;
  output_uri?: string | null;
  type?: string;
};

export type ArtifactDownloadResponse = {
  artifact_id: string;
  url: string;
  expires_in: number;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
};

export async function register(email: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  await ensureResponseOk(res, "注册失败");
  return (await res.json()) as AuthResponse;
}

export async function login(email: string, password: string) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  await ensureResponseOk(res, "登录失败");
  return (await res.json()) as AuthResponse;
}

export async function createCase(payload: PatentCasePayload, token: string) {
  const res = await fetch(`${API_BASE}/cases`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  await ensureResponseOk(res, "创建案件失败");
  return (await res.json()) as PatentCaseResponse;
}

export async function startIngest(
  caseId: string,
  payload: {
    providers?: string[];
    prefer_official?: boolean;
    include_dms_fallback?: boolean;
    trigger_processing?: boolean;
  },
  token: string
) {
  const res = await fetch(`${API_BASE}/cases/${encodeURIComponent(caseId)}/ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  await ensureResponseOk(res, "启动采集失败");
  return (await res.json()) as IngestResponse;
}

export async function getIngestTaskStatus(taskId: string, token: string) {
  const res = await fetch(`${API_BASE}/cases/ingest-tasks/${encodeURIComponent(taskId)}`, {
    method: "GET",
    headers: buildAuthHeader(token),
  });
  await ensureResponseOk(res, "加载采集进度失败");
  return (await res.json()) as IngestTaskStatusResponse;
}

export async function chat(payload: any, token: string) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  await ensureResponseOk(res, "问答请求失败");
  return res.json();
}

function buildAuthHeader(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

function extractErrorMessage(errorBody: unknown, fallback: string) {
  if (typeof errorBody === "object" && errorBody !== null && "detail" in errorBody) {
    const detail = (errorBody as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

async function ensureResponseOk(res: Response, fallbackMessage: string) {
  if (res.ok) return;
  const body = await res.json().catch(() => null);
  throw new Error(extractErrorMessage(body, fallbackMessage));
}

export async function listSources(token: string, jurisdictionCaseId?: string) {
  const query = jurisdictionCaseId
    ? `?jurisdiction_case_id=${encodeURIComponent(jurisdictionCaseId)}`
    : "";
  const res = await fetch(`${API_BASE}/sources${query}`, {
    method: "GET",
    headers: buildAuthHeader(token),
  });
  await ensureResponseOk(res, "加载来源文档失败");
  return (await res.json()) as SourceDocument[];
}

type UploadSourcePayload = {
  token: string;
  jurisdictionCaseId: string;
  docType: string;
  file: File;
  language?: string;
  version?: string;
};

export async function uploadSource(payload: UploadSourcePayload) {
  const formData = new FormData();
  formData.append("jurisdiction_case_id", payload.jurisdictionCaseId);
  formData.append("doc_type", payload.docType);
  if (payload.language) formData.append("language", payload.language);
  if (payload.version) formData.append("version", payload.version);
  formData.append("file", payload.file);

  const res = await fetch(`${API_BASE}/sources/upload`, {
    method: "POST",
    headers: buildAuthHeader(payload.token),
    body: formData,
  });
  await ensureResponseOk(res, "上传来源文档失败");
  return (await res.json()) as SourceDocument;
}

export async function updateSourceIncluded(token: string, sourceId: string, included: boolean) {
  const res = await fetch(`${API_BASE}/sources/${sourceId}?included=${included}`, {
    method: "PATCH",
    headers: buildAuthHeader(token),
  });
  await ensureResponseOk(res, "更新来源文档勾选状态失败");
  return (await res.json()) as { id: string; included: boolean };
}

type CreateArtifactPayload = {
  case_id: string;
  artifact_type: string;
  source_ids?: string[];
  params?: Record<string, unknown>;
};

export async function createArtifact(payload: CreateArtifactPayload, token: string) {
  const res = await fetch(`${API_BASE}/studio/artifacts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...buildAuthHeader(token),
    },
    body: JSON.stringify(payload),
  });
  await ensureResponseOk(res, "创建产物任务失败");
  return (await res.json()) as ArtifactCreateResponse;
}

export async function getArtifactStatus(artifactId: string, token: string) {
  const res = await fetch(`${API_BASE}/studio/artifacts/${artifactId}`, {
    method: "GET",
    headers: buildAuthHeader(token),
  });
  await ensureResponseOk(res, "加载产物状态失败");
  return (await res.json()) as ArtifactStatusResponse;
}

export async function getArtifactDownloadUrl(
  artifactId: string,
  token: string,
  expiresIn = 3600
) {
  const res = await fetch(
    `${API_BASE}/studio/artifacts/${artifactId}/download-url?expires_in=${expiresIn}`,
    {
      method: "GET",
      headers: buildAuthHeader(token),
    }
  );
  await ensureResponseOk(res, "获取产物下载链接失败");
  return (await res.json()) as ArtifactDownloadResponse;
}
