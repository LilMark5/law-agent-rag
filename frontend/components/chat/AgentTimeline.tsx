"use client";

import { Fragment } from "react";
import clsx from "clsx";

export interface ReviewTrace {
  passed: boolean;
  score: number;
  mode: string;
  issues: string[];
}

/**
 * 一次问答的编排轨迹：ChatContainer 在消费 SSE 事件时累积，
 * AgentTimeline 据此派生出 4 个步骤的状态与三路检索的命中情况。
 */
export interface AgentTrace {
  domain?: string;
  domainZh?: string;
  intent?: string;
  keywords?: string[];
  sourcesCount?: number;
  retrievedBy?: string[];
  attempt?: number;
  review?: ReviewTrace;
  unretrieved?: string[];
  currentStep?: string | null;
  /** 每个步骤的耗时（ms），key 为 step 名；值为该步与上一步事件之间的间隔 */
  timings?: Partial<Record<"intent" | "retrieve" | "generate" | "review", number>>;
}

const STEPS = [
  { key: "intent", label: "识别意图" },
  { key: "retrieve", label: "检索知识" },
  { key: "generate", label: "生成回答" },
  { key: "review", label: "引用审查" },
] as const;

type StepKey = (typeof STEPS)[number]["key"];

const CHANNELS = [
  { key: "bm25", label: "BM25" },
  { key: "vector", label: "向量" },
  { key: "graph", label: "图谱" },
] as const;

type ChannelKey = (typeof CHANNELS)[number]["key"];

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function stepStatus(trace: AgentTrace, key: StepKey): "pending" | "running" | "done" | "failed" {
  switch (key) {
    case "intent":
      if (trace.domain || trace.domainZh) return "done";
      return trace.currentStep === "intent" ? "running" : "pending";
    case "retrieve":
      if (trace.sourcesCount != null) return "done";
      return trace.currentStep === "retrieve" ? "running" : "pending";
    case "generate":
      if ((trace.attempt ?? 0) >= 1) return "done";
      return trace.currentStep === "generate" ? "running" : "pending";
    case "review":
      if (trace.review) return trace.review.passed ? "done" : "failed";
      return trace.currentStep === "review" ? "running" : "pending";
  }
}

function channelHit(trace: AgentTrace, key: ChannelKey): boolean | null {
  if (trace.sourcesCount == null) return null;
  return (trace.retrievedBy ?? []).includes(key);
}

export function AgentTimeline({ trace }: { trace: AgentTrace }) {
  const started =
    trace.domain != null ||
    trace.sourcesCount != null ||
    trace.attempt != null ||
    trace.review != null ||
    trace.currentStep != null;

  if (!started) return null;

  return (
    <div className="agent-timeline" role="status" aria-live="polite">
      <div className="step-track">
        {STEPS.map((step, idx) => {
          const status = stepStatus(trace, step.key);
          return (
            <Fragment key={step.key}>
              <div
                className={clsx(
                  "step",
                  status === "running" && "active",
                  status === "done" && "done",
                  status === "failed" && "failed",
                )}
              >
                <span className="step-num">{String(idx + 1).padStart(2, "0")}</span>
                <span className="step-label">{step.label}</span>
                {trace.timings?.[step.key] != null && (
                  <span className="step-ms">{fmtMs(trace.timings[step.key]!)}</span>
                )}
              </div>
              {idx < STEPS.length - 1 && <span className="step-sep" />}
            </Fragment>
          );
        })}
      </div>

      <div className="timeline-meta">
        {trace.domainZh && (
          <span className={clsx("domain-badge", trace.domain)}>{trace.domainZh}</span>
        )}
        {trace.intent && <span className="timeline-chip">意图：{trace.intent}</span>}
        {trace.keywords && trace.keywords.length > 0 && (
          <span className="timeline-chip">关键词：{trace.keywords.join("、")}</span>
        )}
        {trace.sourcesCount != null && (
          <span className="timeline-chip">召回 {trace.sourcesCount} 条</span>
        )}
        {trace.attempt && trace.attempt > 1 && (
          <span className="timeline-chip warn">第 {trace.attempt} 版</span>
        )}
        {trace.review && (
          <span className={clsx("timeline-chip", trace.review.passed ? "ok" : "warn")}>
            {trace.review.passed
              ? `审查通过 ${trace.review.score.toFixed(2)}`
              : "审查未通过"}
          </span>
        )}
        {trace.unretrieved && trace.unretrieved.length > 0 && (
          <span className="timeline-chip warn">
            未召回(非编造)：{trace.unretrieved.join("、")}
          </span>
        )}
      </div>

      <div className="retrieval-channels">
        <span className="channels-label">检索通道</span>
        {CHANNELS.map((channel) => {
          const hit = channelHit(trace, channel.key);
          return (
            <span
              key={channel.key}
              className={clsx("channel-chip", hit === true && "hit", hit === false && "miss")}
            >
              {channel.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
