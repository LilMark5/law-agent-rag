export const DEMO_MATTER_ID = "demo-matter";

export const routes = {
  home: "/",
  about: "/about",
  workspace: "/workspace",
  consultation: (matterId = DEMO_MATTER_ID) => `/consultation/${matterId}`,
  analysis: (matterId = DEMO_MATTER_ID) => `/analysis/${matterId}`,
  graph: (matterId = DEMO_MATTER_ID) => `/graph/${matterId}`,
  evidence: (matterId = DEMO_MATTER_ID) => `/evidence/${matterId}`,
  history: "/history",
  admin: "/admin",
  settings: "/settings",
} as const;

export const primaryNavItems = [
  // 对话页用的是独立顶栏布局，不在 AppShell 内；
  // 但侧边栏必须保留回对话的入口，否则进入工作台后就无法返回首页。
  { key: "chat", label: "对话", href: routes.home, mark: "话" },
  { key: "workspace", label: "工作台", href: routes.workspace, mark: "工" },
  { key: "consultation", label: "咨询", href: routes.consultation(), mark: "咨" },
  { key: "analysis", label: "分析", href: routes.analysis(), mark: "析" },
  { key: "graph", label: "图谱", href: routes.graph(), mark: "图" },
  { key: "evidence", label: "证据", href: routes.evidence(), mark: "证" },
  { key: "history", label: "历史", href: routes.history, mark: "史" },
  { key: "admin", label: "运维", href: routes.admin, mark: "运" },
  { key: "settings", label: "设置", href: routes.settings, mark: "设" },
  { key: "about", label: "关于", href: routes.about, mark: "关" },
];
