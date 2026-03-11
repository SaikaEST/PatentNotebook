"use client";

import { useEffect, useMemo, useState } from "react";

import { chat, listSources } from "../lib/api";
import {
  CASE_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
} from "../lib/workspace";

type Citation = {
  source_id: string;
  chunk_id: string;
  page?: number | null;
  quote: string;
};

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
  citations: Citation[];
};

const seedMessages: Message[] = [
  {
    id: "m1",
    role: "assistant",
    content: "先同步来源 ID，再提问时间线或权利要求变化。",
    citations: [],
  },
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

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>(seedMessages);
  const [token, setToken] = useState("");
  const [caseId, setCaseId] = useState("");
  const [sourceIdsInput, setSourceIdsInput] = useState("");
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    const savedCaseId = localStorage.getItem(CASE_STORAGE_KEY) || "";
    const savedSourceIds = localStorage.getItem(INCLUDED_SOURCE_IDS_STORAGE_KEY) || "[]";

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

    const savedJurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
    if (!savedToken.trim() || !savedJurisdictionCaseId.trim() || parsedIds.length === 0) {
      return;
    }

    let active = true;
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

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    localStorage.setItem(CASE_STORAGE_KEY, caseId);
  }, [caseId]);

  const sourceIds = useMemo(() => parseSourceIds(sourceIdsInput), [sourceIdsInput]);

  const syncFromLocalIncluded = async () => {
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
    } catch {
      setErrorMessage("读取本地来源编号失败。");
    }
  };

  const syncFromSourcesApi = async () => {
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }

    const jurisdictionCaseId = localStorage.getItem(JURISDICTION_CASE_STORAGE_KEY) || "";
    if (!jurisdictionCaseId.trim()) {
      setErrorMessage("请先在来源文档中填写欧洲专利编号。");
      return;
    }

    setIsSyncing(true);
    setErrorMessage("");
    try {
      const sources = await listSources(token.trim(), jurisdictionCaseId.trim());
      const ids = sources.filter((item) => item.included).map((item) => item.id);
      setSourceIdsInput(ids.join(", "));
      localStorage.setItem(INCLUDED_SOURCE_IDS_STORAGE_KEY, JSON.stringify(ids));
    } catch (error) {
      setErrorMessage(toMessage(error, "从来源文档同步来源编号失败。"));
    } finally {
      setIsSyncing(false);
    }
  };

  const send = async () => {
    if (!question.trim()) return;
    if (!token.trim()) {
      setErrorMessage("请先登录。");
      return;
    }
    if (!caseId.trim()) {
      setErrorMessage("请输入案件编号。");
      return;
    }

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: question.trim(),
      citations: [],
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsSending(true);
    setErrorMessage("");

    try {
      const response = await chat(
        {
          case_id: caseId.trim(),
          question: question.trim(),
          source_ids: sourceIds,
          include_notes_as_sources: false,
        },
        token.trim()
      );

      const assistantContent =
        typeof response?.answer === "string" && response.answer ? response.answer : "后端未返回回答内容。";
      const assistantCitations = Array.isArray(response?.citations) ? response.citations : [];
      const missingReason = response?.missing_reason ? `\n\n缺失原因：${response.missing_reason}` : "";

      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: `${assistantContent}${missingReason}`,
        citations: assistantCitations,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setQuestion("");
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
          <span>案件编号</span>
          <input value={caseId} onChange={(e) => setCaseId(e.target.value)} placeholder="专利案件唯一标识" />
        </label>
        <label className="field-group">
          <span>来源编号列表</span>
          <input
            value={sourceIdsInput}
            onChange={(e) => setSourceIdsInput(e.target.value)}
            placeholder="多个来源编号，用逗号分隔"
          />
        </label>
        <div className="inline-actions">
          <button type="button" onClick={syncFromLocalIncluded}>
            使用本地已勾选来源
          </button>
          <button type="button" onClick={syncFromSourcesApi} disabled={isSyncing}>
            {isSyncing ? "同步中..." : "从来源文档同步"}
          </button>
        </div>
      </div>

      {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}

      <div className="chat-window">
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role === "user" ? "user" : ""}`}>
            <div>{msg.content}</div>
            {msg.citations.length > 0 && (
              <div className="citations">
                {msg.citations.map((citation, idx) => (
                  <span className="citation" key={`${citation.chunk_id}-${idx}`}>
                    {citation.source_id}:{citation.page ?? "-"}
                  </span>
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
