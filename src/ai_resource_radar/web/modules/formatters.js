/* Human-readable labels shared by resource, pricing, and tracking views. */

export function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "尚未刷新";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

export function compactNumber(value) {
  return Number(value).toLocaleString("zh-CN", {
    maximumFractionDigits: Number(value) % 1 ? 1 : 0,
  });
}

export function resetLabel(value) {
  return {
    daily: "每天", weekly: "每周", monthly: "每月", one_time: "一次性",
    variable: "动态", unknown: "周期待确认",
  }[value] || "周期待确认";
}

export function kindLabel(value) {
  return { token: "Token", gpu: "GPU 算力", grant: "资助" }[value] || value;
}

export function actionQuota(resource) {
  const value = resource.quota_value;
  const unit = resource.quota_unit || "";
  const period = { daily: "天", weekly: "周", monthly: "月" }[resource.reset_period];
  if (value === null || value === undefined) {
    if (unit.includes("model-specific")) return "按模型给额度";
    if (resource.reset_period === "variable") return "动态额度";
    return unit || "免费额度";
  }
  const number = compactNumber(value);
  if (unit === "USD compute credit") return `$${number}${period ? ` / ${period}` : ""}`;
  if (unit === "neurons") return `${number}${period ? ` / ${period}` : " Neurons"}`;
  if (unit === "GPU hours") return `${number} 小时${period ? ` / ${period}` : ""}`;
  if (unit === "GPU minutes") return `${number} GPU 分钟${period ? ` / ${period}` : ""}`;
  if (unit === "requests") return `${number} 次请求${period ? ` / ${period}` : ""}`;
  return `${number} ${unit}${period ? ` / ${period}` : ""}`.trim();
}

export function guide(resource) {
  return resource.details && typeof resource.details === "object" ? resource.details : {};
}

export function benefitSummary(resource) {
  return guide(resource).benefit_summary || resource.eligibility || `${actionQuota(resource)} 免费额度`;
}

export function usageSteps(resource) {
  const steps = guide(resource).usage_steps;
  return Array.isArray(steps) ? steps.filter((step) => typeof step === "string" && step.trim()) : [];
}

export function caveats(resource) {
  const items = guide(resource).caveats;
  return Array.isArray(items) ? items.filter((item) => typeof item === "string" && item.trim()) : [];
}


export function formatUsd(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  const digits = number >= 10 ? 2 : number >= 1 ? 3 : number >= 0.01 ? 4 : 6;
  return `$${number.toLocaleString("zh-CN", { maximumFractionDigits: digits })}`;
}

export function formatContext(value) {
  if (!value) return "未记录";
  if (value >= 1_000_000) return `${compactNumber(value / 1_000_000)}M`;
  if (value >= 1_000) return `${compactNumber(value / 1_000)}K`;
  return compactNumber(value);
}

export function changeLabel(changeType) {
  return {
    added: "新增",
    updated: "信息更新",
    quota_changed: "额度变化",
    limits_changed: "限制变化",
    removed: "已下架",
    expiring: "即将到期",
  }[changeType] || changeType;
}
