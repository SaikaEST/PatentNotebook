"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import ChatPanel from "../../components/ChatPanel";
import SourcesPanel from "../../components/SourcesPanel";
import StudioPanel from "../../components/StudioPanel";
import { RESETTABLE_WORKSPACE_KEYS, TOKEN_STORAGE_KEY } from "../../lib/workspace";

const WORKSPACE_KEYS = [TOKEN_STORAGE_KEY, ...RESETTABLE_WORKSPACE_KEYS];

export default function AssistantPage() {
  const router = useRouter();
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY) || "";
    if (!token.trim()) {
      router.replace("/");
      return;
    }
    setIsReady(true);
  }, [router]);

  const handleLogout = () => {
    WORKSPACE_KEYS.forEach((key) => {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    });
    router.replace("/");
  };

  if (!isReady) {
    return null;
  }

  return (
    <main>
      <header className="header">
        <div>
          <h1>专利审查助手</h1>
          <span className="tag">案件工作台</span>
        </div>
        <button type="button" className="ghost-button" onClick={handleLogout}>
          退出登录
        </button>
      </header>
      <section className="layout">
        <SourcesPanel />
        <ChatPanel />
        <StudioPanel />
      </section>
    </main>
  );
}
