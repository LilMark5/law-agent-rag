import type { MatterStatus } from "@/lib/types";

export function statusLabel(status: MatterStatus) {
  const labels: Record<MatterStatus, string> = {
    draft: "草稿",
    in_review: "审查中",
    verified: "已核验",
    partial: "部分完成",
    stale: "来源过期",
    error: "需要关注",
  };
  return labels[status];
}

export function matterTypeLabel(type: string) {
  const labels: Record<string, string> = {
    contract: "合同",
    labor: "劳动",
    corporate: "公司",
    tort: "侵权",
    compliance: "合规",
    general: "通用",
  };
  return labels[type] ?? type;
}

export function sourceTypeLabel(type: string) {
  const labels: Record<string, string> = {
    statute: "法条",
    law: "法条",
    case: "案例",
    memo: "材料",
    excerpt: "摘录",
    evidence: "证据",
  };
  return labels[type] ?? type;
}

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
