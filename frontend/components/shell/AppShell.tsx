import Link from "next/link";
import type { ReactNode } from "react";
import { primaryNavItems, routes } from "@/lib/routes";

export function AppShell({
  active,
  children,
  fill = false,
}: {
  active: string;
  children: ReactNode;
  /** 撑满顶栏以下的剩余高度，滚动交给内部容器（对话页用） */
  fill?: boolean;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="主导航">
        <Link className="brand" href={routes.home}>
          <span className="brand-mark">律</span>
          <span>
            <strong>LilMark</strong>
            <small>法律 Agent 助手</small>
          </span>
        </Link>

        <nav className="nav-list">
          {primaryNavItems.map((item) => (
            <Link
              aria-current={active === item.key ? "page" : undefined}
              className={`nav-item ${active === item.key ? "active" : ""}`}
              href={item.href}
              key={item.key}
            >
              <span className="nav-mark" aria-hidden="true">
                {item.mark}
              </span>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="profile-card">
          <span className="avatar" aria-hidden="true">
            律
          </span>
          <span>
            <strong>Lil Mark</strong>
            <small>AI Agent 工程 · 项目演示</small>
          </span>
        </div>
      </aside>

      <main className={`shell-main${fill ? " shell-main-fill" : ""}`}>
        <header className="topbar">
          <span
            style={{ color: "var(--color-ink-mute)", fontSize: "12px" }}
          >
            多角色 Agent 编排 · 知识图谱增强检索
          </span>
          <div className="topbar-actions">
            <Link className="button ghost" href={routes.admin}>
              系统状态
            </Link>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
