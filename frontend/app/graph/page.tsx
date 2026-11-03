import { GraphExplorer } from "@/components/graph/GraphExplorer";
import { AppShell } from "@/components/shell/AppShell";

export default function GraphPage() {
  return (
    <AppShell active="graph">
      <GraphExplorer />
    </AppShell>
  );
}
