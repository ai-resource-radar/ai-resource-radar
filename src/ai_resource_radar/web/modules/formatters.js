/* Human-readable labels shared by resource, pricing, and tracking views. */

import {
  benefitSummary as sharedBenefitSummary,
  caveats as sharedCaveats,
  compactNumber as sharedCompactNumber,
  formatTime as sharedFormatTime,
  formatUsd as sharedFormatUsd,
  kindLabel as sharedKindLabel,
  quotaText,
  resetLabel as sharedResetLabel,
  usageSteps as sharedUsageSteps,
} from "/ai-radar-shared/formatters.js";

export function formatTime(value) {
  return sharedFormatTime(value, "zh-CN");
}

export function compactNumber(value) {
  return sharedCompactNumber(value, "zh-CN");
}

export function resetLabel(value) {
  return sharedResetLabel(value, "zh-CN");
}

export function kindLabel(value) {
  return sharedKindLabel(value, "zh-CN");
}

export function actionQuota(resource) {
  return quotaText(resource, "zh-CN");
}

export function guide(resource) {
  return resource.details && typeof resource.details === "object" ? resource.details : {};
}

export function benefitSummary(resource) {
  return sharedBenefitSummary(resource, "zh-CN");
}

export function usageSteps(resource) {
  return sharedUsageSteps(resource, "zh-CN");
}

export function caveats(resource) {
  return sharedCaveats(resource, "zh-CN");
}


export function formatUsd(value) {
  return sharedFormatUsd(value, "zh-CN");
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
