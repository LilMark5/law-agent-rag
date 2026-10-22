import { EvidencePanel } from "@/components/evidence/EvidencePanel";
import { MatterHeader } from "@/components/matter/MatterHeader";
import { AppShell } from "@/components/shell/AppShell";
import { currentMatter, evidenceItems } from "@/lib/data";
import { sourceTypeLabel } from "@/lib/status";

export default function EvidencePage() {
  return (
    <AppShell active="evidence">
      <div className="page-stack">
        <MatterHeader matter={currentMatter} />
        <div className="evidence-center">
          <section className="panel source-list-panel">
            <div className="section-heading">
              <div>
                <h2>证据中心</h2>
                <p>查阅法条、案例、摘录以及本案专属的原始材料。</p>
              </div>
              <div className="chip-row">
                <span className="tag">相关度</span>
                <span className="tag">权威性</span>
              </div>
            </div>
            <div className="evidence-list">
              {evidenceItems.map((item) => (
                <article className="source-card static" key={item.id}>
                  <span className="source-type">{sourceTypeLabel(item.type)}</span>
                  <h3>{item.title}</h3>
                  <small>{item.authority} · {item.date}</small>
                  <p>{item.excerpt}</p>
                </article>
              ))}
            </div>
          </section>
          <EvidencePanel items={evidenceItems} selectedId="e1" />
        </div>
      </div>
    </AppShell>
  );
}
