import type { Metadata } from "next";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "LilMark 法律咨询助手",
  description: "多智能体协作 · GraphRAG 检索 · 结构化法律问答",
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
