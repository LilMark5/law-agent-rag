import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { matters } from "@/lib/data";
import { StatusBadge } from "@/components/matter/MatterHeader";
import { routes } from "@/lib/routes";

export default function HistoryPage() {
  return (
    <AppShell active="history">
      <section className="panel">
        <div className="section-heading">
          <div>
            <h1>事项历史</h1>
            <p>浏览、重新打开、复制或导出过往的法律事项。</p>
          </div>
          <input className="inline-search" placeholder="筛选已保存的事项…" />
        </div>
        <div className="history-table">
          {matters.map((matter) => (
            <Link className="history-row" href={routes.consultation(matter.id)} key={matter.id}>
              <strong>{matter.title}</strong>
              <span>{matter.jurisdiction}</span>
              <StatusBadge status={matter.status} />
              <span>{matter.updatedAt}</span>
            </Link>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
