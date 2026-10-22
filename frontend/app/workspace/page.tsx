import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { matters } from "@/lib/data";
import { matterTypeLabel } from "@/lib/status";
import { StatusBadge } from "@/components/matter/MatterHeader";
import { routes } from "@/lib/routes";

export default function WorkspacePage() {
  return (
    <AppShell active="workspace">
      <div className="page-stack">
        <section className="workspace-hero">
          <div>
            <div className="eyebrow">工作台</div>
            <h1>每一个结论，都落在证据上。</h1>
            <p>发起结构化咨询、核查权威依据，并把长期事项的脉络与历史整理在同一处。</p>
          </div>
          <Link className="button primary" href={routes.consultation()}>
            新建事项
          </Link>
        </section>

        <div className="workspace-grid">
          <section className="panel wide-panel">
            <div className="section-heading">
              <div>
                <h2>最近事项</h2>
                <p>打开事项，继续咨询、证据审查或结构化分析。</p>
              </div>
              <input className="inline-search" placeholder="搜索事项…" />
            </div>
            <div className="matter-list">
              {matters.map((matter) => (
                <Link className="matter-card" href={routes.consultation(matter.id)} key={matter.id}>
                  <div>
                    <StatusBadge status={matter.status} />
                    <h3>{matter.title}</h3>
                    <p>{matter.summary}</p>
                  </div>
                  <div className="matter-card-meta">
                    <span>{matterTypeLabel(matter.matterType)}</span>
                    <span>{matter.jurisdiction}</span>
                    <span>{matter.updatedAt}</span>
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <aside className="side-stack">
            <section className="panel">
              <div className="panel-title">事项模板</div>
              {["劳动合同解除审查", "合同风险备忘录", "合规问题地图"].map((template) => (
                <button className="template-row" key={template} type="button">
                  {template}
                </button>
              ))}
            </section>
            <section className="panel">
              <div className="panel-title">知识库新鲜度</div>
              <div className="metric-large">92%</div>
              <p>核心法律语料已于 18 分钟前同步，2 个采集任务待复核。</p>
            </section>
            <section className="panel">
              <div className="panel-title">系统状态</div>
              <div className="status-line success">图谱检索在线</div>
              <div className="status-line warning">2 个数据源导入失败</div>
            </section>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
