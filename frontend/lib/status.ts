export function graphTypeLabel(type: string) {
  const labels: Record<string, string> = {
    issue: "争点",
    law: "法条",
    case: "案例",
    behavior: "行为",
    responsibility: "责任",
  };
  return labels[type] ?? type;
}
