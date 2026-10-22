import type { EvidenceItem } from "@/lib/types";
import { sourceTypeLabel } from "@/lib/status";

export function CitationChip({
  label,
  type,
}: {
  label: string;
  type: string;
}) {
  return (
    <button className={`citation-chip ${type}`} type="button">
      {label}
    </button>
  );
}

export function EvidenceSourceCard({
  item,
  selected,
}: {
  item: EvidenceItem;
  selected?: boolean;
}) {
  return (
    <button className={`source-card ${selected ? "selected" : ""}`} type="button">
      <span className="source-type">{sourceTypeLabel(item.type)}</span>
      <strong>{item.title}</strong>
      <small>
        {item.authority} · {item.date}
      </small>
      <p>{item.excerpt}</p>
      <span className="confidence">{Math.round(item.relevanceScore * 100)}% 相关</span>
    </button>
  );
}

export function EvidencePanel({
  items,
  selectedId,
}: {
  items: EvidenceItem[];
  selectedId?: string;
}) {
  const selected = items.find((item) => item.id === selectedId) ?? items[0];

  return (
    <aside className="panel evidence-panel">
      <div className="panel-title">已核验来源</div>
      <div className="evidence-list compact">
        {items.map((item) => (
          <EvidenceSourceCard item={item} key={item.id} selected={item.id === selected.id} />
        ))}
      </div>
      <div className="source-viewer">
        <span className="source-type">{sourceTypeLabel(selected.type)}</span>
        <h3>{selected.title}</h3>
        <dl className="metadata-grid">
          <div>
            <dt>来源机构</dt>
            <dd>{selected.authority}</dd>
          </div>
          <div>
            <dt>管辖</dt>
            <dd>{selected.jurisdiction}</dd>
          </div>
          <div>
            <dt>日期</dt>
            <dd>{selected.date}</dd>
          </div>
          <div>
            <dt>相关度</dt>
            <dd>{Math.round(selected.relevanceScore * 100)}%</dd>
          </div>
        </dl>
        <blockquote>{selected.excerpt}</blockquote>
        <div className="chip-row">
          {selected.relatedIssues.map((issue) => (
            <span className="tag" key={issue}>
              {issue}
            </span>
          ))}
        </div>
      </div>
    </aside>
  );
}
