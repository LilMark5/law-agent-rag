import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DomainBadge } from "@/components/ui/Badge";
import { SourceDetail } from "@/lib/api";

interface AssistantMessageProps {
  content: string;
  domain?: string;
  domain_zh?: string;
  sources?: string[];
  sourcesDetail?: SourceDetail[];
  streaming?: boolean;
}

const CHANNEL_LABELS: Record<string, string> = {
  bm25: "BM25",
  vector: "向量",
  graph: "图谱",
  fallback: "兜底",
};

function channelLabel(key?: string): string {
  if (!key) return "";
  return CHANNEL_LABELS[key] ?? key;
}

function SourceCard({ src }: { src: SourceDetail }) {
  const title =
    src.type === "law"
      ? `${src.law_name ?? ""} ${src.article_number ?? ""}`.trim()
      : src.case_id ?? "";

  return (
    <div className={`source-card source-card--${src.type}`}>
      <div className="source-card-head">
        <span className={`source-card-badge source-card-badge--${src.type}`}>
          {src.type === "law" ? "法条" : "类案"}
        </span>
        <span className="source-card-title">{title}</span>
        {src.retrieved_by && (
          <span className="source-card-channel">{channelLabel(src.retrieved_by)}</span>
        )}
      </div>

      {src.type === "law" && src.chapter_path ? (
        <div className="source-card-meta">{src.chapter_path}</div>
      ) : null}

      {src.type === "case" && (
        <>
          {src.crime ? <div className="source-card-meta">罪名：{src.crime}</div> : null}
          {src.fact ? <div className="source-card-body">{src.fact}</div> : null}
          {src.judgment ? (
            <div className="source-card-judgment">判决：{src.judgment}</div>
          ) : null}
        </>
      )}
    </div>
  );
}

export function AssistantMessage({
  content,
  domain,
  domain_zh,
  sources = [],
  sourcesDetail,
  streaming = false,
}: AssistantMessageProps) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const hasDetail = !!sourcesDetail && sourcesDetail.length > 0;
  const count = hasDetail ? sourcesDetail!.length : sources.length;

  return (
    <div className="msg">
      {domain && domain_zh && (
        <DomainBadge domain={domain} domain_zh={domain_zh} />
      )}
      <div className={`msg-assistant-bubble ${streaming ? "cursor-blink" : ""}`}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
      </div>

      {count > 0 && (
        <div className="msg">
          <button
            className="msg-sources-toggle"
            onClick={() => setSourcesOpen(!sourcesOpen)}
            type="button"
          >
            {sourcesOpen ? "收起引用" : `引用来源 (${count})`}
          </button>
          {sourcesOpen &&
            (hasDetail ? (
              <div className="msg-sources-cards">
                {sourcesDetail!.map((src, i) => (
                  <SourceCard key={i} src={src} />
                ))}
              </div>
            ) : (
              <ul className="msg-sources">
                {sources.map((src, i) => (
                  <li key={i}>{src}</li>
                ))}
              </ul>
            ))}
        </div>
      )}
    </div>
  );
}
