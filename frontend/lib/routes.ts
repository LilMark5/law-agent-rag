export const routes = {
  home: "/",
  about: "/about",
  graph: "/graph",
  history: "/history",
  admin: "/admin",
} as const;

export const primaryNavItems = [
  // 对话页用 AppShell fill 布局，内部自行管理滚动；但必须保留回对话的入口。
  { key: "chat", label: "对话", href: routes.home, mark: "话" },
  { key: "graph", label: "图谱", href: routes.graph, mark: "图" },
  { key: "history", label: "历史", href: routes.history, mark: "史" },
  { key: "admin", label: "运维", href: routes.admin, mark: "运" },
  { key: "about", label: "关于", href: routes.about, mark: "关" },
];
