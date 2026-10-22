"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/shell/AppShell";
import {
  fetchHistoryDetail,
  fetchHistoryList,
  type HistorySession,
  type HistorySummary,
} from "@/lib/api";

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const emptyStyle: React.CSSProperties = {
  padding: "24px 4px",
  fontSize: "13px",
  color: "var(--color-ink-mute)",
};

export default function HistoryPage() {
  const [sessions, setSessions] = useState<HistorySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<HistorySession | null>(null);

  useEffect(() => {
    fetchHistoryList()
      .then(setSessions)
      .catch(() => setError("历史记录加载失败，请确认后端已启动。"));
  }, []);

  const toggle = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetail(null);
    try {
      setDetail(await fetchHistoryDetail(id));
    } catch {
      setError("会话详情加载失败。");
    }
  };

  return (
    <AppShell active="history">
      <section className="panel">
        <div className="section-heading">
          <div>
            <h1>对话历史</h1>
            <p>多轮问答会话，按最近更新排序；由后端持久化，刷新页面仍在。</p>
          </div>
        </div>

        {error ? (
          <p style={emptyStyle}>{error}</p>
        ) : sessions === null ? (
          <p style={emptyStyle}>加载中…</p>
        ) : sessions.length === 0 ? (
          <p style={emptyStyle}>暂无对话记录。去「对话」页提问后，会话会自动出现在这里。</p>
        ) : (
          <div className="history-table">
            {sessions.map((s) => (
              <div key={s.id}>
                <div
                  className="history-row"
                  onClick={() => toggle(s.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && toggle(s.id)}
                >
                  <strong>{s.title}</strong>
                  <span>{s.turns} 轮</span>
                  <span></span>
                  <span>{formatTime(s.updated_at)}</span>
                </div>
                {expandedId === s.id && (
                  <div
                    style={{
                      padding: "8px 6px 16px",
                      borderTop: "1px solid var(--color-rule)",
                    }}
                  >
                    {detail ? (
                      detail.turns.map((t, i) => (
                        <div key={i} style={{ margin: "12px 0" }}>
                          <div
                            style={{
                              fontSize: "12px",
                              fontWeight: 600,
                              color: "var(--color-ink)",
                            }}
                          >
                            问：{t.question}
                          </div>
                          <div
                            style={{
                              fontSize: "12px",
                              color: "var(--color-ink-soft)",
                              whiteSpace: "pre-wrap",
                              marginTop: 4,
                            }}
                          >
                            {t.answer}
                          </div>
                        </div>
                      ))
                    ) : (
                      <span style={{ fontSize: "12px", color: "var(--color-ink-mute)" }}>
                        加载中…
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  );
}
