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
  presentationFor as sharedPresentationFor,
} from "/ai-radar-shared/formatters.js";
import { dashboardLocale, tr } from "/ai-radar-assets/modules/i18n.js";

export function formatTime(value) {
  return sharedFormatTime(value, dashboardLocale());
}

export function compactNumber(value) {
  return sharedCompactNumber(value, dashboardLocale());
}

export function resetLabel(value) {
  return sharedResetLabel(value, dashboardLocale());
}

export function kindLabel(value) {
  return sharedKindLabel(value, dashboardLocale());
}

export function actionQuota(resource) {
  return quotaText(resource, dashboardLocale());
}

export function guide(resource) {
  const details = resource.details && typeof resource.details === "object" ? resource.details : {};
  return { ...details, ...sharedPresentationFor(resource, dashboardLocale()) };
}

export function benefitSummary(resource) {
  return sharedBenefitSummary(resource, dashboardLocale());
}

export function usageSteps(resource) {
  return sharedUsageSteps(resource, dashboardLocale());
}

export function caveats(resource) {
  return sharedCaveats(resource, dashboardLocale());
}


export function formatUsd(value) {
  return sharedFormatUsd(value, dashboardLocale());
}

export function formatContext(value) {
  if (!value) return tr("Not recorded", "未记录");
  if (value >= 1_000_000) return `${compactNumber(value / 1_000_000)}M`;
  if (value >= 1_000) return `${compactNumber(value / 1_000)}K`;
  return compactNumber(value);
}

export function changeLabel(changeType) {
  return {
    added: tr("Added", "新增"),
    updated: tr("Updated", "信息更新"),
    quota_changed: tr("Quota changed", "额度变化"),
    limits_changed: tr("Limits changed", "限制变化"),
    removed: tr("Removed", "已下架"),
    expiring: tr("Expiring", "即将到期"),
  }[changeType] || changeType;
}
