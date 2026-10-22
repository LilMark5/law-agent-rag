import { matterTypeLabel, statusLabel } from "@/lib/status";
import type { MatterSummary } from "@/lib/types";

export function StatusBadge({ status }: { status: MatterSummary["status"] }) {
  return <span className={`status-badge ${status}`}>{statusLabel(status)}</span>;
}

export function MatterHeader({ matter }: { matter: MatterSummary }) {
  return (
    <section className="matter-header">
      <div>
        <div className="eyebrow">事项状态</div>
        <h1>{matter.title}</h1>
        <p>{matter.summary}</p>
      </div>
      <div className="matter-meta">
        <StatusBadge status={matter.status} />
        <span>{matterTypeLabel(matter.matterType)}</span>
        <span>{matter.jurisdiction}</span>
        <span>{matter.updatedAt}</span>
        <button className="button secondary" type="button">
          保存
        </button>
        <button className="button primary" type="button">
          导出
        </button>
      </div>
    </section>
  );
}

export function MatterOutlinePanel() {
  const sections = [
    ["概览", "解除路径、事实背景、当前状态"],
    ["事实", "3 个已固定事实，2 个待核实事实"],
    ["争点", "录用条件明示、举证责任、程序完整性"],
    ["依据", "1 条法律、1 个案例、1 份材料"],
    ["备注", "建议补充入职签收与考核规则送达"],
  ];

  return (
    <aside className="panel outline-panel">
      <div className="panel-title">事项大纲</div>
      {sections.map(([title, body]) => (
        <button className="outline-item" key={title} type="button">
          <strong>{title}</strong>
          <span>{body}</span>
        </button>
      ))}
    </aside>
  );
}
