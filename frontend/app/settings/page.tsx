import { AppShell } from "@/components/shell/AppShell";

export default function SettingsPage() {
  return (
    <AppShell active="settings">
      <section className="panel settings-panel">
        <div className="section-heading">
          <div>
            <h1>设置</h1>
            <p>调整工作台的显示密度、证据面板与审查默认项。</p>
          </div>
        </div>
        {["紧凑排版", "保持证据面板常开", "导出前必须完成风险审查"].map((label, index) => (
          <label className="settings-row" key={label}>
            <span>
              <strong>{label}</strong>
              <small>{index === 0 ? "长时间阅读时使用更紧凑的间距。" : "该偏好保存在本地。"}</small>
            </span>
            <input defaultChecked={index !== 0} type="checkbox" />
          </label>
        ))}
      </section>
    </AppShell>
  );
}
