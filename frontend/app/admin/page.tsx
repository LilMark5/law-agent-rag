"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { fetchSystemStats, type SystemStats } from "@/lib/api";

function formatNum(n: number) {
  return n.toLocaleString("zh-CN");
}

export default function AdminPage() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchSystemStats()
      .then((s) => alive && setStats(s))
      .catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, []);

  const graph = stats?.graph;
  const maxArticles = stats?.topLawBooks[0]?.articles ?? 0;
  const avgCasesPerLaw =
    graph && graph.laws > 0 ? (graph.relations / graph.laws).toFixed(1) : "—";

  return (
    <AppShell active="admin">
      <div className="page-stack">
        <section className="workspace-hero compact">
          <div>
            <div className="eyebrow">运维</div>
            <h1>系统与数据健康</h1>
            <p>以下数字实时读取自 Neo4j 与本地索引文件，不再使用模拟值。</p>
          </div>
        </section>

        {error && (
          <div className="status-line warning">
            无法连接后端服务，请确认 8000 端口已启动。
          </div>
        )}

        <section className="metrics-grid">
          {[
            {
              label: "法条节点",
              value: graph ? formatNum(graph.laws) : "—",
              detail: graph ? `覆盖 ${graph.lawBooks} 部法规` : "加载中…",
            },
            {
              label: "案例节点",
              value: graph ? formatNum(graph.cases) : "—",
              detail: "CAIL2018 刑事案例",
            },
            {
              label: "APPLIES 关系",
              value: graph ? formatNum(graph.relations) : "—",
              detail: `平均每法条 ${avgCasesPerLaw} 条案例`,
            },
            {
              label: "向量索引",
              value:
                stats && stats.vectorIndex.exists
                  ? `${stats.vectorIndex.sizeMb} MB`
                  : "未构建",
              detail: stats
                ? `FAISS · ${stats.embedding.dimension} 维`
                : "加载中…",
            },
          ].map((metric) => (
            <article className="panel metric-card" key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <p>{metric.detail}</p>
            </article>
          ))}
        </section>

        <div className="admin-columns">
          <section className="panel">
            <div className="panel-title">法规条数分布</div>
            {stats && stats.topLawBooks.length > 0 ? (
              <div className="bar-list">
                {stats.topLawBooks.map((book) => (
                  <div className="bar-row" key={book.name}>
                    <span className="bar-name" title={book.name}>
                      {book.name.replace("中华人民共和国", "")}
                    </span>
                    <span className="bar-track">
                      <i
                        style={{
                          width: `${maxArticles ? (book.articles / maxArticles) * 100 : 0}%`,
                        }}
                      />
                    </span>
                    <b>{book.articles}</b>
                  </div>
                ))}
              </div>
            ) : (
              <p className="graph-empty">
                {graph && !graph.available ? "Neo4j 未连接" : "加载中…"}
              </p>
            )}
          </section>

          <section className="panel">
            <div className="panel-title">运行配置</div>
            {stats ? (
              <div className="config-list">
                <div className="config-row">
                  <span>Neo4j 图谱</span>
                  <b className={graph?.available ? "ok" : "warn"}>
                    {graph?.available ? "已连接" : "未连接"}
                  </b>
                </div>
                <div className="config-row">
                  <span>向量索引</span>
                  <b className={stats.vectorIndex.exists ? "ok" : "warn"}>
                    {stats.vectorIndex.exists ? "已加载" : "缺失（检索降级）"}
                  </b>
                </div>
                <div className="config-row">
                  <span>生成模型</span>
                  <b>{stats.llm.model || "—"}</b>
                </div>
                <div className="config-row">
                  <span>Embedding</span>
                  <b>{stats.embedding.model || "—"}</b>
                </div>
                <div className="config-row">
                  <span>融合策略</span>
                  <b>
                    {stats.retrieval.fusion.toUpperCase()} · top{stats.retrieval.finalTopK} · {stats.retrieval.graphHop} 跳
                  </b>
                </div>
                <div className="config-row">
                  <span>引用审查</span>
                  <b>
                    {stats.review.enabled
                      ? `${stats.review.mode === "llm" ? "LLM" : "规则"}模式 · 重试 ${stats.review.max_retry}`
                      : "已关闭"}
                  </b>
                </div>
                <div className="config-row">
                  <span>LLM 凭证</span>
                  <b className={stats.llm.configured ? "ok" : "warn"}>
                    {stats.llm.configured ? "已配置" : "缺失"}
                  </b>
                </div>
                <div className="config-row">
                  <span>Embedding 凭证</span>
                  <b className={stats.embedding.configured ? "ok" : "warn"}>
                    {stats.embedding.configured ? "已配置" : "缺失"}
                  </b>
                </div>
              </div>
            ) : (
              <p className="graph-empty">加载中…</p>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
