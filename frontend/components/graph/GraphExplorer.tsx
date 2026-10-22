"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchGraphStats,
  fetchSubgraph,
  type GraphStats,
  type Subgraph,
  type SubgraphNode,
} from "@/lib/api";
import { graphTypeLabel } from "@/lib/status";

/** 力导向布局：简单斥力 + 弹簧引力，迭代若干轮得到一个可看的分布。 */
function layout(nodes: SubgraphNode[], edges: Subgraph["edges"]) {
  const positions = new Map<string, { x: number; y: number }>();
  const W = 100;
  const H = 100;
  nodes.forEach((n, i) => {
    const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
    positions.set(n.id, {
      x: W / 2 + Math.cos(angle) * 22,
      y: H / 2 + Math.sin(angle) * 22,
    });
  });

  const repulsion = 18;
  const springLen = 14;
  const springK = 0.04;
  for (let iter = 0; iter < 60; iter++) {
    const forces = new Map<string, { x: number; y: number }>();
    nodes.forEach((n) => forces.set(n.id, { x: 0, y: 0 }));

    // 斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const pa = positions.get(a.id)!;
        const pb = positions.get(b.id)!;
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        if (dist > 60) continue;
        const f = repulsion / (dist * dist);
        dx /= dist;
        dy /= dist;
        forces.get(a.id)!.x += dx * f;
        forces.get(a.id)!.y += dy * f;
        forces.get(b.id)!.x -= dx * f;
        forces.get(b.id)!.y -= dy * f;
      }
    }

    // 弹簧引力
    for (const edge of edges) {
      const a = positions.get(edge.from);
      const b = positions.get(edge.to);
      if (!a || !b) continue;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (dist - springLen) * springK;
      dx /= dist;
      dy /= dist;
      forces.get(edge.from)!.x += dx * f;
      forces.get(edge.from)!.y += dy * f;
      forces.get(edge.to)!.x -= dx * f;
      forces.get(edge.to)!.y -= dy * f;
    }

    // 应用位移 + 边界钳制
    for (const n of nodes) {
      const p = positions.get(n.id)!;
      const f = forces.get(n.id)!;
      p.x = Math.max(4, Math.min(W - 4, p.x + f.x * 0.08));
      p.y = Math.max(4, Math.min(H - 4, p.y + f.y * 0.08));
    }
  }
  return positions;
}

const DEFAULT_ARTICLE = "第二百六十四条";
const DEFAULT_LAW = "刑法";

export function GraphExplorer() {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [subgraph, setSubgraph] = useState<Subgraph | null>(null);
  const [query, setQuery] = useState("");
  const [lawQuery, setLawQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    fetchGraphStats()
      .then((s) => mountedRef.current && setStats(s))
      .catch(() => mountedRef.current && setStats(null));
  }, []);

  useEffect(() => {
    // 首屏加载一个默认条号的子图，让画布有真实内容
    fetchSubgraph(DEFAULT_ARTICLE, DEFAULT_LAW)
      .then((g) => mountedRef.current && setSubgraph(g))
      .catch(() => mountedRef.current && setSubgraph(null));
  }, []);

  const positions = useMemo(
    () => (subgraph ? layout(subgraph.nodes, subgraph.edges) : new Map()),
    [subgraph],
  );

  const runQuery = async () => {
    const article = query.trim();
    if (!article) return;
    setLoading(true);
    setError(null);
    setSelectedId(null);
    try {
      const g = await fetchSubgraph(article, lawQuery.trim() || undefined);
      if (mountedRef.current) setSubgraph(g);
    } catch {
      if (mountedRef.current) setError("子图查询失败，请确认后端与 Neo4j 已启动。");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  const selected: SubgraphNode | undefined = subgraph?.nodes.find(
    (n) => n.id === selectedId,
  );

  return (
    <div className="graph-layout">
      <aside className="panel graph-filter">
        <div className="panel-title">图谱筛选</div>
        <label className="field">
          <span>按条号检索</span>
          <input
            placeholder="如：第二百六十四条 / 第39条"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runQuery()}
          />
        </label>
        <label className="field">
          <span>法名收窄（可选）</span>
          <input
            placeholder="如：刑法 / 民法典"
            value={lawQuery}
            onChange={(e) => setLawQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runQuery()}
          />
        </label>
        <button className="button primary graph-query-btn" type="button" onClick={runQuery} disabled={loading}>
          {loading ? "查询中…" : "查询子图"}
        </button>

        <div className="graph-stats">
          <div className="panel-title">知识库统计</div>
          {stats ? (
            <>
              <div className="stat-row">
                <span>法条节点</span>
                <b>{stats.laws.toLocaleString()}</b>
              </div>
              <div className="stat-row">
                <span>案例节点</span>
                <b>{stats.cases.toLocaleString()}</b>
              </div>
              <div className="stat-row">
                <span>APPLIES 关系</span>
                <b>{stats.relations.toLocaleString()}</b>
              </div>
              {!stats.available && (
                <p className="graph-empty">Neo4j 未连接，显示为 0</p>
              )}
            </>
          ) : (
            <p className="graph-empty">统计加载中…</p>
          )}
        </div>

        <div className="legend">
          <span>
            <i className="dot law" />
            {graphTypeLabel("law")}
          </span>
          <span>
            <i className="dot case" />
            {graphTypeLabel("case")}
          </span>
        </div>
      </aside>

      <section className="graph-canvas" aria-label="知识图谱">
        {subgraph && subgraph.available ? (
          <>
            <div className="graph-subgraph-meta">
              子图：{subgraph.nodes.length} 节点 · {subgraph.edges.length} 关系
              {subgraph.nodes.some((n) => n.type === "law") &&
                ` · ${subgraph.nodes.filter((n) => n.type === "law")[0]?.law_name ?? ""}`}
            </div>
            <svg viewBox="0 0 100 100" role="img" aria-label="图谱关系">
            {subgraph.edges.map((edge, i) => {
              const from = positions.get(edge.from);
              const to = positions.get(edge.to);
              if (!from || !to) return null;
              return (
                <line
                  key={`${edge.from}-${edge.to}-${i}`}
                  x1={from.x}
                  x2={to.x}
                  y1={from.y}
                  y2={to.y}
                />
              );
            })}
            {subgraph.nodes.map((node) => {
              const p = positions.get(node.id);
              if (!p) return null;
              return (
                <g
                  className={`graph-node ${node.type} ${selectedId === node.id ? "selected" : ""}`}
                  key={node.id}
                  onClick={() => setSelectedId(node.id)}
                  role="button"
                  tabIndex={0}
                >
                  <circle cx={p.x} cy={p.y} r={selectedId === node.id ? 8 : 6} />
                  <text x={p.x} y={p.y + 13}>
                    {node.label}
                  </text>
                </g>
              );
            })}
            </svg>
          </>
        ) : (
          <div className="graph-empty-state">
            {subgraph && !subgraph.available
              ? stats && stats.available === false
                ? "Neo4j 未连接，请先启动 Neo4j。"
                : `未命中「${subgraph.article}」对应的节点。换个条号试试（支持：第二百六十四条 / 第264条 / 264）。`
              : "加载图谱…"}
          </div>
        )}
        {error && <div className="graph-error">{error}</div>}
        <div className="canvas-controls">
          <button className="button secondary" type="button" onClick={() => setSelectedId(null)}>
            取消选择
          </button>
        </div>
      </section>

      <aside className="panel node-inspector">
        <div className="panel-title">节点详情</div>
        {selected ? (
          <>
            <span className={`source-type ${selected.type}`}>
              {graphTypeLabel(selected.type)}
            </span>
            <h2>{selected.type === "law" ? `${selected.law_name} ${selected.label}` : selected.label}</h2>
            {selected.type === "law" ? (
              <p>{selected.content || "（条文内容略）"}</p>
            ) : (
              <p>
                {selected.crime ? `罪名：${selected.crime}` : ""}
                {selected.judgment ? `\n判决：${selected.judgment}` : ""}
              </p>
            )}
            <div className="metadata-grid">
              <div>
                <dt>{selected.type === "law" ? "所在章节" : "罪名"}</dt>
                <dd>{selected.type === "law" ? selected.chapter || "—" : selected.crime || "—"}</dd>
              </div>
              <div>
                <dt>关联关系</dt>
                <dd>
                  {subgraph?.edges.filter((e) => e.from === selected.id || e.to === selected.id).length ?? 0}
                </dd>
              </div>
            </div>
          </>
        ) : (
          <p className="graph-empty">点击节点查看详情</p>
        )}
      </aside>
    </div>
  );
}
