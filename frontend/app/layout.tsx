import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "专利审查助手",
  description: "企业级专利审查流程分析工作台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
