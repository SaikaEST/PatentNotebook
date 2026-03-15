"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";

import { getSourceViewer, SourceViewerResponse } from "../../../../lib/api";
import { TOKEN_STORAGE_KEY } from "../../../../lib/workspace";

function toMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export default function SourceViewerPage() {
  const params = useParams<{ sourceId: string }>();
  const searchParams = useSearchParams();
  const [token, setToken] = useState("");
  const [viewer, setViewer] = useState<SourceViewerResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const highlightedChunkId = searchParams.get("chunk") || "";
  const highlightedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    setToken(savedToken);
  }, []);

  useEffect(() => {
    if (!token.trim() || !params?.sourceId) return;

    let cancelled = false;
    setIsLoading(true);
    setErrorMessage("");

    void (async () => {
      try {
        const response = await getSourceViewer(token.trim(), params.sourceId);
        if (cancelled) return;
        setViewer(response);
      } catch (error) {
        if (cancelled) return;
        setErrorMessage(toMessage(error, "加载文档内容失败。"));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [params?.sourceId, token]);

  useEffect(() => {
    if (!highlightedChunkId || !highlightedRef.current) return;
    highlightedRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlightedChunkId, viewer]);

  const pageTitle = useMemo(() => {
    if (!viewer) return "文档查看";
    return viewer.file_name?.trim() || viewer.doc_type;
  }, [viewer]);

  return (
    <main className="viewer-page">
      <section className="viewer-shell">
        <div className="viewer-header">
          <div className="viewer-meta">
            <h1>{pageTitle}</h1>
            {viewer ? (
              <p>
                类型：{viewer.doc_type} | 语言：{viewer.language || "-"} | 分块数：{viewer.chunks.length}
              </p>
            ) : null}
          </div>
        </div>

        {isLoading ? <p className="panel-message info">加载中...</p> : null}
        {errorMessage ? <p className="panel-message error">{errorMessage}</p> : null}

        {viewer ? (
          <div className="viewer-content">
            {viewer.chunks.length === 0 ? (
              <p className="panel-message info">当前文档还没有解析后的文本内容。</p>
            ) : null}
            {viewer.chunks.map((chunk) => {
              const highlighted = chunk.id === highlightedChunkId;
              return (
                <article
                  key={chunk.id}
                  ref={highlighted ? highlightedRef : null}
                  className={`viewer-chunk ${highlighted ? "is-highlighted" : ""}`}
                  id={`chunk-${chunk.id}`}
                >
                  <div className="viewer-chunk-meta">
                    <strong>Chunk #{chunk.chunk_index}</strong>
                    <span>
                      {chunk.page_no !== null && chunk.page_no !== undefined
                        ? `第 ${chunk.page_no} 页`
                        : "页码未知"}
                    </span>
                  </div>
                  <pre>{chunk.text}</pre>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
    </main>
  );
}
