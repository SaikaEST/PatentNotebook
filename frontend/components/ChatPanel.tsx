"use client";

import { useEffect, useMemo, useState } from "react";

import { chat, listSources, SourceCitation, SourceDocument } from "../lib/api";
import {
  CASE_STORAGE_KEY,
  CHAT_MESSAGES_STORAGE_KEY,
  CHAT_QUESTION_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
} from "../lib/workspace";

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
  citations: SourceCitation[];
};

const DEFAULT_ASSISTANT_MESSAGE = "请先同步已勾选的来源文档，再提问时间线、审查意见或权利要求变化。";

const seedMessages: Message[] = [
  {
    id: "m1",
    role: "assistant",
    content: DEFAULT_ASSISTANT_MESSAGE,
    citations: [],
  },
];

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function getSourceLabel(source: SourceDocument): string {
  return source.file_name?.trim() || source.doc_type || source.id;
}

function getCitationHref(citation: SourceCitation): string {
  return citation.viewer_url || `/assistant/sources/${citation.source_id}?chunk=${citation.chunk_id}`;
}

function parseSavedMessages(raw: string | null): Message[] {
  if (!raw) return seedMessages;
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return seedMessages;
    const messages = parsed.filter((item): item is Message => {
      if (!item || typeof item !== "object") return false;
      const candidate = item as Partial<Message>;
      return (
        typeof candidate.id === "string" &&
        (candidate.role === "assistant" || candidate.role === "user") &&
        typeof candidate.content === "string" &&
        Array.isArray(candidate.citations) &&
        candidate.content.trim().length > 0
      );
    });
    return messages.length > 0 ? messages : seedMessages;
  } catch {
    return seedMessages;
  }
}

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>(seedMessages);
  const [token, setToken] = useState("");
  const [caseId, setCaseId] = useState("");
  const [selectedSources, setSelectedSources] = useState<SourceDocument[]>([]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [hasRestored, setHasRestored] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    const savedCaseId = localStorage.getItem(CASE_STORAGE_KEY) || "";
    const savedJurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
    const savedQuestion = localStorage.getItem(CHAT_QUESTION_STORAGE_KEY) || "";
    const restoredMessages = parseSavedMessages(localStorage.getItem(CHAT_MESSAGES_STORAGE_KEY));

    setToken(savedToken);
    setCaseId(savedCaseId);
    setQuestion(savedQuestion);
    setMessages(restoredMessages);
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(restoredMessages));

    if (savedToken.trim() && savedJurisdictionCaseId.trim()) {
      void syncSelectedSources(savedToken.trim(), savedJurisdictionCaseId.trim(), false);
    }
    setHasRestored(true);
  }, []);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(CASE_STORAGE_KEY, caseId);
  }, [caseId, hasRestored]);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(CHAT_QUESTION_STORAGE_KEY, question);
  }, [question, hasRestored]);

  useEffect(() => {
    if (!hasRestored) return;
    localStorage.setItem(CHAT_MESSAGES_STORAGE_KEY, JSON.stringify(messages));
  }, [messages, hasRestored]);

  const selectedSourceIds = useMemo(() => selectedSources.map((item) => item.id), [selectedSources]);

  async function syncSelectedSources(
    activeToken?: string,
    jurisdictionCaseId?: string,
    showMessage = true
  ) {
    const nextToken = (activeToken ?? token).trim();
    const nextJurisdictionCaseId = (
      jurisdictionCaseId ?? localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) ?? ""
    ).trim();

    if (!nextToken) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!nextJurisdictionCaseId) {
      setErrorMessage("请先在来源文档面板中填写司法辖区案件 ID。");
      return;
    }

    setIsSyncing(true);
    setErrorMessage("");
    if (showMessage) setSuccessMessage("");

    try {
      const sources = await listSources(nextToken, nextJurisdictionCaseId);
      const includedSources = sources.filter((item) => item.included);
      setSelectedSources(includedSources);
      localStorage.setItem(
        INCLUDED_SOURCE_IDS_STORAGE_KEY,
        JSON.stringify(includedSources.map((item) => item.id))
      );
      if (showMessage) {
        setSuccessMessage(`已同步 ${includedSources.length} 份已勾选文档。`);
      }
    } catch (error) {
      setErrorMessage(toMessage(error, "同步来源文档失败。"));
    } finally {
      setIsSyncing(false);
    }
  }

  const send = async () => {
    if (!question.trim()) return;
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!caseId.trim()) {
      setErrorMessage("请输入案件 ID。");
      return;
    }
    if (selectedSourceIds.length === 0) {
      setErrorMessage("当前没有已勾选的来源文档，请先同步来源文档。");
      return;
    }

    const prompt = question.trim();
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: prompt,
      citations: [],
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsSending(true);
    setErrorMessage("");
    setSuccessMessage("");

    try {
      const response = await chat(
        {
          case_id: caseId.trim(),
          question: prompt,
          source_ids: selectedSourceIds,
          include_notes_as_sources: false,
        },
        token.trim()
      );

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: response.answer || "后端未返回回答内容。",
        citations: Array.isArray(response.citations) ? response.citations : [],
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setQuestion("");
      if (response.missing && response.missing_reason) {
        setErrorMessage(response.missing_reason);
      }
    } catch (error) {
      setErrorMessage(toMessage(error, "问答请求失败。"));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <section className="panel">
      <h2>智能问答</h2>
      <div className="source-controls">
        <label className="field-group">
          <span>案件 ID</span>
          <input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="专利案件唯一标识" />
        </label>
        <div className="task-progress-card">
          <div className="task-progress-header">
            <strong>问答来源文档</strong>
            <span>{selectedSources.length} 份</span>
          </div>
          {selectedSources.length > 0 ? (
            <div className="citations">
              {selectedSources.map((source) => (
                <span className="citation" key={source.id} title={source.id}>
                  {getSourceLabel(source)}
                </span>
              ))}
            </div>
          ) : (
            <p className="panel-message info">当前没有已勾选文档，请先在左侧来源文档面板中勾选。</p>
          )}
        </div>
        <div className="inline-actions">
          <button type="button" onClick={() => void syncSelectedSources()} disabled={isSyncing}>
            {isSyncing ? "同步中..." : "同步已勾选文档"}
          </button>
        </div>
      </div>

      {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}
      {successMessage ? <p className="panel-message success">{successMessage}</p> : null}

      <div className="chat-window">
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role === "user" ? "user" : ""}`}>
            <div>{msg.content}</div>
            {msg.citations.length > 0 && (
              <div className="citations">
                {msg.citations.map((citation, idx) => (
                  <a
                    className="citation"
                    key={`${citation.chunk_id}-${idx}`}
                    href={getCitationHref(citation)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {citation.source_name || citation.source_id}
                    {citation.page !== null && citation.page !== undefined ? ` 第 ${citation.page} 页` : ""}
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="input-row">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="例如：总结审查意见要点与答复策略"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button type="button" onClick={() => void send()} disabled={isSending}>
          {isSending ? "发送中..." : "发送"}
        </button>
      </div>
    </section>
  );
}
