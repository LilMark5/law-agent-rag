import { EvidencePanel } from "@/components/evidence/EvidencePanel";
import { MatterHeader } from "@/components/matter/MatterHeader";
import { AppShell } from "@/components/shell/AppShell";
import { analysisSections, currentMatter, evidenceItems } from "@/lib/data";

export default function AnalysisPage() {
  return (
    <AppShell active="analysis">
      <div className="page-stack">
        <MatterHeader matter={currentMatter} />
        <div className="analysis-layout">
          <section className="analysis-main">
            {analysisSections.map((section) => (
              <article className="analysis-card" key={section.title}>
                <div>
                  <span className="eyebrow">{section.meta}</span>
                  <h2>{section.title}</h2>
                </div>
                <p>{section.body}</p>
                <div className="card-actions">
                  <button className="button secondary" type="button">编辑</button>
                  <button className="button secondary" type="button">固定</button>
                  <button className="button secondary" type="button">引用</button>
                </div>
              </article>
            ))}
            <section className="risk-panel">
              <strong>风险与未知项</strong>
              <p>缺少录用条件签收、考核规则送达与工会通知记录。在证据链补齐之前，结论应保持为草稿。</p>
            </section>
          </section>
          <EvidencePanel items={evidenceItems} selectedId="e2" />
        </div>
      </div>
    </AppShell>
  );
}
