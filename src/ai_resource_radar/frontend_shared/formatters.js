/* Normalized offer labels used by local API and public JSON adapters. */

const LABELS = {
  "zh-CN": {
    unknown: "待确认", supported: "大陆可用", unsupported: "大陆不支持",
    noCard: "无需信用卡", card: "需要信用卡", cardUnknown: "信用卡待确认",
    official: "官方核验", community: "社区基线", daily: "每天", weekly: "每周",
    monthly: "每月", one_time: "一次性", variable: "动态", token: "Token",
    gpu: "GPU 算力", grant: "资助",
  },
  en: {
    unknown: "Unknown", supported: "Mainland supported", unsupported: "Mainland unavailable",
    noCard: "No card", card: "Card required", cardUnknown: "Card unknown",
    official: "Official", community: "Community", daily: "Daily", weekly: "Weekly",
    monthly: "Monthly", one_time: "One time", variable: "Variable", token: "Token",
    gpu: "GPU compute", grant: "Grant",
  },
};

const AVAILABILITY_LABELS = {
  "zh-CN": { supported: "所选地区已确认支持", unsupported: "所选地区明确不支持", unknown: "所选地区待确认", unfiltered: "未按地区筛选", global: "全球可用" },
  en: { supported: "Confirmed in selected region", unsupported: "Unavailable in selected region", unknown: "Region availability unknown", unfiltered: "No region filter", global: "Global availability" },
};

function labels(locale) { return LABELS[locale === "en" ? "en" : "zh-CN"]; }

export function textValue(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

export function compactNumber(value, locale = "zh-CN") {
  const number = Number(value);
  if (!Number.isFinite(number)) return textValue(value);
  return number.toLocaleString(locale, { maximumFractionDigits: number % 1 ? 2 : 0 });
}

export function formatTime(value, locale = "zh-CN") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return locale === "en" ? "Not refreshed" : "尚未刷新";
  return new Intl.DateTimeFormat(locale, {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

export function formatUsd(value, locale = "zh-CN") {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return textValue(value);
  const digits = number >= 10 ? 2 : number >= 1 ? 3 : number >= .01 ? 4 : 6;
  return `$${number.toLocaleString(locale, { maximumFractionDigits: digits })}`;
}

export function resetLabel(value, locale = "zh-CN") {
  const copy = labels(locale);
  return copy[value] || copy.unknown;
}

export function kindLabel(value, locale = "zh-CN") {
  return labels(locale)[value] || textValue(value);
}

export function verificationLabel(value, locale = "zh-CN") {
  return ["official_api", "official_page"].includes(value) ? labels(locale).official : labels(locale).community;
}

export function mainlandLabel(value, locale = "zh-CN") {
  return labels(locale)[value] || labels(locale).unknown;
}

export function availabilityLabel(value, locale = "zh-CN", scope = "unknown") {
  const copy = AVAILABILITY_LABELS[locale === "en" ? "en" : "zh-CN"];
  if ((!value || value === "unfiltered") && scope === "global") return copy.global;
  return copy[value] || copy.unfiltered;
}

export function cardLabel(value, locale = "zh-CN") {
  const copy = labels(locale);
  return value === "no" ? copy.noCard : value === "yes" ? copy.card : copy.cardUnknown;
}

export function presentationFor(resource, locale = "zh-CN") {
  const publicPresentation = resource?.presentations || resource?.presentation;
  if (publicPresentation && typeof publicPresentation === "object") {
    if (locale === "en") return publicPresentation.en || {};
    return publicPresentation[locale] || publicPresentation["zh-CN"] || publicPresentation.en || {};
  }
  return resource?.details && typeof resource.details === "object" ? resource.details : {};
}

export function quotaText(resource, locale = "zh-CN") {
  const value = resource?.quota_value;
  const unit = resource?.quota_unit || "";
  const period = { daily: locale === "en" ? "day" : "天", weekly: locale === "en" ? "week" : "周", monthly: locale === "en" ? "month" : "月" }[resource?.reset_period];
  if (value === null || value === undefined) {
    if (unit.includes("model-specific")) return locale === "en" ? "Model-specific quota" : "按模型给额度";
    if (resource?.reset_period === "variable") return locale === "en" ? "Variable free quota" : "动态免费额度";
    return unit || (locale === "en" ? "Free quota" : "免费额度");
  }
  const number = compactNumber(value, locale);
  if (/^USD .*credit$/i.test(unit)) return `$${number}${period ? ` / ${period}` : ""}`;
  if (unit === "GPU hours") return `${number} ${locale === "en" ? "GPU hours" : "GPU 小时"}${period ? ` / ${period}` : ""}`;
  if (unit === "GPU minutes") return `${number} ${locale === "en" ? "GPU minutes" : "GPU 分钟"}${period ? ` / ${period}` : ""}`;
  if (unit === "requests") return `${number} ${locale === "en" ? "requests" : "次请求"}${period ? ` / ${period}` : ""}`;
  return `${number} ${unit}${period ? ` / ${period}` : ""}`.trim();
}

export function benefitSummary(resource, locale = "zh-CN") {
  const presentation = presentationFor(resource, locale);
  const fallbackEligibility = locale === "en" ? "" : resource?.eligibility;
  return presentation.benefit_summary || fallbackEligibility || `${quotaText(resource, locale)} ${locale === "en" ? "free" : "免费额度"}`;
}

export function usageSteps(resource, locale = "zh-CN") {
  const steps = presentationFor(resource, locale).usage_steps;
  return Array.isArray(steps) ? steps.filter((item) => typeof item === "string" && item.trim()) : [];
}

export function caveats(resource, locale = "zh-CN") {
  const presentation = presentationFor(resource, locale);
  const items = presentation.limitations || presentation.caveats;
  return Array.isArray(items) ? items.filter((item) => typeof item === "string" && item.trim()) : [];
}

export function actionUrl(resource, locale = "zh-CN") {
  return presentationFor(resource, locale).action_url || resource?.homepage_url || resource?.evidence?.source_url || "";
}
