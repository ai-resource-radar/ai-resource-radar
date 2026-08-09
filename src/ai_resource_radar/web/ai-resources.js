"use strict";

const summaryRoot = document.querySelector("#radar-summary");
const featuredRoot = document.querySelector("#featured-resources");
const featuredSection = document.querySelector("#featured-section");
const resultsRoot = document.querySelector("#radar-results");
const refreshButton = document.querySelector("#refresh-radar");
const refreshState = document.querySelector("#refresh-state");
const queryInput = document.querySelector("#radar-query");
const verifiedOnly = document.querySelector("#verified-only");
const noCard = document.querySelector("#no-card");
const freeImageGeneration = document.querySelector("#free-image-generation");
const mainlandSupported = document.querySelector("#mainland-supported");
const mainlandUnknown = document.querySelector("#mainland-unknown");
const mainlandUnsupported = document.querySelector("#mainland-unsupported");
const filters = document.querySelector(".radar-filters");
const filterToggle = document.querySelector("#toggle-filters");
const tabs = [...document.querySelectorAll("[data-view]")];
const dialog = document.querySelector("#offer-dialog");
const detailRoot = document.querySelector("#offer-detail");
const closeDialogButton = document.querySelector("#close-offer-dialog");
const heroPickTitle = document.querySelector("#hero-pick-title");
const heroPickNote = document.querySelector("#hero-pick-note");
const lastVerified = document.querySelector("#last-verified");
const sourceHealth = document.querySelector("#source-health");
const sourceHealthBar = document.querySelector("#source-health-bar");
const healthySourceCount = document.querySelector("#healthy-source-count");
const failedSourceCount = document.querySelector("#failed-source-count");
const changePreview = document.querySelector("#change-preview");
const catalogTitle = document.querySelector("#catalog-title");
const catalogCaption = document.querySelector("#catalog-caption");
const heroEyebrow = document.querySelector("#hero-eyebrow");
const heroTitle = document.querySelector("#hero-title");
const heroCopy = document.querySelector("#hero-copy");
const heroPickLabel = document.querySelector("#hero-pick-label");
const pricingControls = document.querySelector("#pricing-controls");
const pricingSort = document.querySelector("#pricing-sort");
const pricingDirection = document.querySelector("#pricing-direction");
const pricingProvider = document.querySelector("#pricing-provider");
const tokenPriceControls = [...document.querySelectorAll(".token-price-control")];
const tokenVerification = document.querySelector("#token-verification");
const tokenMinContext = document.querySelector("#token-min-context");
const tokenMaxTypical = document.querySelector("#token-max-typical");
const tokenMaxInput = document.querySelector("#token-max-input");
const tokenMaxOutput = document.querySelector("#token-max-output");
const tokenCache = document.querySelector("#token-cache");
const gpuPriceControls = [...document.querySelectorAll(".gpu-price-control")];
const gpuModel = document.querySelector("#gpu-model");
const gpuMinVram = document.querySelector("#gpu-min-vram");
const gpuMaxHourly = document.querySelector("#gpu-max-hourly");
const gpuBilling = document.querySelector("#gpu-billing");
const gpuTier = document.querySelector("#gpu-tier");
const gpuPriceMode = document.querySelector("#gpu-price-mode");
const gpuHours = document.querySelector("#gpu-hours");
const pricingFilterSummary = document.querySelector("#pricing-filter-summary");
const priceCompareBar = document.querySelector("#price-compare-bar");
const priceCompareCount = document.querySelector("#price-compare-count");
const openPriceCompare = document.querySelector("#open-price-compare");
const browserGrid = document.querySelector(".browser-grid");
const radarSidebar = document.querySelector(".radar-sidebar");

const knownViews = new Set([
  "recommended", "token", "gpu", "token-prices", "gpu-prices", "grant", "poster", "changes",
]);
const hashView = window.location.hash.replace("#", "");
let currentView = knownViews.has(hashView) ? hashView : "recommended";
let searchTimer = null;
let refreshTimer = null;
const comparedPrices = new Map();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function fetchJson(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || "request_failed");
  return payload;
}

function formatTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "尚未刷新";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function compactNumber(value) {
  return Number(value).toLocaleString("zh-CN", {
    maximumFractionDigits: Number(value) % 1 ? 1 : 0,
  });
}

function resetLabel(value) {
  return {
    daily: "每天",
    weekly: "每周",
    monthly: "每月",
    one_time: "一次性",
    variable: "动态",
    unknown: "周期待确认",
  }[value] || "周期待确认";
}

function kindLabel(value) {
  return { token: "Token", gpu: "GPU 算力", grant: "资助" }[value] || value;
}

function quotaLabel(resource) {
  if (resource.quota_value === null || resource.quota_value === undefined) {
    return resource.quota_unit || "额度随账号或供需变化";
  }
  return `${compactNumber(resource.quota_value)} ${resource.quota_unit || ""}`.trim();
}

function actionQuota(resource) {
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

function guide(resource) {
  return resource.details && typeof resource.details === "object" ? resource.details : {};
}

function benefitSummary(resource) {
  return guide(resource).benefit_summary || resource.eligibility || `${actionQuota(resource)} 免费额度`;
}

function usageSteps(resource) {
  const steps = guide(resource).usage_steps;
  return Array.isArray(steps) ? steps.filter((step) => typeof step === "string" && step.trim()) : [];
}

function caveats(resource) {
  const items = guide(resource).caveats;
  return Array.isArray(items) ? items.filter((item) => typeof item === "string" && item.trim()) : [];
}

function safeLink(label, url, className) {
  try {
    const target = new URL(url);
    if (!["http:", "https:"].includes(target.protocol)) return null;
    const link = element("a", className, label);
    link.href = target.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    link.addEventListener("click", (event) => event.stopPropagation());
    return link;
  } catch {
    return null;
  }
}

function metric(label, value, note) {
  const card = element("article", "radar-metric");
  card.append(
    element("span", "", label),
    element("strong", "", value),
    element("small", "", note),
  );
  return card;
}

function providerInitials(provider) {
  const overrides = {
    OpenRouter: "OR",
    Groq: "GQ",
    Cloudflare: "CF",
    "Google Gemini": "GM",
    "Google Colab": "GC",
    "Hugging Face": "HF",
    "Lightning AI": "LI",
    Modal: "MO",
    Kaggle: "KG",
  };
  if (overrides[provider]) return overrides[provider];
  return provider
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase() || "AI";
}

function cardBadges(resource) {
  const badges = [];
  badges.push(resource.requires_card === "no" ? ["无需信用卡", ""] : ["信用卡待确认", ""]);
  if (resource.free_image_generation) badges.push(["免费生图", "good"]);
  if (resource.reset_period && !["unknown", "variable"].includes(resource.reset_period)) {
    badges.push([`${resetLabel(resource.reset_period)}重置`, ""]);
  }
  badges.push(
    resource.mainland_status === "supported"
      ? ["大陆可用", "good"]
      : resource.mainland_status === "unsupported"
        ? ["大陆不支持", ""]
        : ["大陆待确认", ""],
  );
  return badges;
}

function openDialog() {
  if (!dialog.open) dialog.showModal();
}

function appendPolicyGuide(resource, options = {}) {
  const resourceGuide = guide(resource);
  const policy = element("section", "policy-hero");
  policy.append(
    element("span", "policy-kicker", "你能白嫖到"),
    element("strong", "policy-amount", actionQuota(resource)),
    element("p", "policy-summary", benefitSummary(resource)),
  );
  const badges = element("div", "offer-badges");
  cardBadges(resource).forEach(([text, className]) => badges.append(element("span", className, text)));
  policy.append(badges);
  detailRoot.append(policy);

  const values = [
    ["恢复周期", resetLabel(resource.reset_period)],
    ["信用卡", resource.requires_card === "no" ? "不需要" : resource.requires_card === "yes" ? "需要" : "待确认"],
    ["大陆情况", resource.mainland_status === "supported" ? "可用" : resource.mainland_status === "unsupported" ? "官方不支持" : "待确认"],
    ["最近核验", formatTime(resource.last_seen_at)],
  ];
  const grid = element("div", "detail-grid compact");
  values.forEach(([label, value]) => {
    const item = element("div");
    item.append(element("span", "", label), element("strong", "", value));
    grid.append(item);
  });
  detailRoot.append(grid);

  const steps = usageSteps(resource);
  if (steps.length) {
    const section = element("section", "guide-section");
    section.append(
      element("span", "guide-eyebrow", `怎么操作 · ${steps.length} 步`),
      element("h3", "", "照着做就能开始用"),
    );
    const list = element("ol", "policy-steps");
    steps.forEach((step) => list.append(element("li", "", step)));
    section.append(list);
    detailRoot.append(section);
  }

  if (resourceGuide.best_for) {
    const bestFor = element("section", "policy-note best-for");
    bestFor.append(element("strong", "", "适合做什么"), element("p", "", resourceGuide.best_for));
    detailRoot.append(bestFor);
  }

  const warnings = caveats(resource);
  if (warnings.length) {
    const warning = element("section", "policy-note warning");
    warning.append(element("strong", "", "领取前注意"));
    const list = element("ul");
    warnings.forEach((item) => list.append(element("li", "", item)));
    warning.append(list);
    detailRoot.append(warning);
  }

  if (!options.hideActions) {
    const actions = element("div", "policy-actions");
    const primary = safeLink(
      resourceGuide.action_label || "去使用",
      resourceGuide.action_url || resource.homepage_url,
      "policy-primary-action",
    );
    const source = safeLink("查看官方政策 ↗", resource.homepage_url, "policy-secondary-action");
    if (primary) actions.append(primary);
    if (source && (!primary || source.href !== primary.href)) actions.append(source);
    if (actions.childElementCount) detailRoot.append(actions);
  }
}

function appendEvidence(resource) {
  const disclosure = element("details", "evidence-disclosure");
  disclosure.append(element("summary", "", "查看官方核验依据与排序原因"));
  const reasons = element("div", "evidence-box");
  (resource.priority_reasons || []).forEach((reason) => {
    reasons.append(element("p", "", `• ${reason}`));
  });
  if (resource.evidence) {
    reasons.append(
      element("span", "evidence-label", "来源摘录"),
      element("p", "", resource.evidence.evidence_excerpt || "来源已记录"),
    );
  }
  disclosure.append(reasons);
  detailRoot.append(disclosure);
}

function showOffer(resource) {
  detailRoot.replaceChildren();
  const tier = element("span", "tier", resource.priority_tier);
  tier.dataset.tier = resource.priority_tier;
  const copy = element("div");
  copy.append(
    element("h2", "", resource.title),
    element("p", "offer-provider", resource.provider),
  );
  const heading = element("div", "offer-heading");
  heading.append(tier, copy);
  detailRoot.append(heading);
  appendPolicyGuide(resource);
  appendEvidence(resource);
  openDialog();
}

function showProvider(resources) {
  detailRoot.replaceChildren();
  const provider = resources[0].provider;
  const heading = element("div", "offer-heading");
  heading.append(
    element("span", "tier", providerInitials(provider)),
    element("div", "", undefined),
  );
  const copy = heading.lastElementChild;
  copy.append(
    element("h2", "", provider),
    element("p", "offer-provider", `${resources.length} 项官方免费资源，共用下面这套领取方式`),
  );
  detailRoot.append(heading);
  appendPolicyGuide(resources[0]);

  const modelHeading = element("div", "provider-list-heading");
  modelHeading.append(
    element("h3", "", `可用资源（${resources.length}）`),
    element("span", "", "点开可查看模型参数与单项证据"),
  );
  const list = element("div", "provider-dialog-list");
  resources.forEach((resource) => {
    const button = element("button", "provider-dialog-item");
    button.type = "button";
    const text = element("span");
    text.append(
      element("strong", "", resource.title),
      element("small", "", `${kindLabel(resource.kind)} · ${actionQuota(resource)}`),
    );
    button.append(text, element("span", "provider-arrow", "›"));
    button.addEventListener("click", () => showOffer(resource));
    list.append(button);
  });
  detailRoot.append(modelHeading, list);
  openDialog();
}

function activateCard(card, action) {
  card.tabIndex = 0;
  card.addEventListener("click", action);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  });
}

function featureCard(resource, primary) {
  const card = element("article", `feature-card${primary ? " primary" : ""}`);
  const tier = element("span", "feature-tier", resource.priority_tier);
  tier.dataset.tier = resource.priority_tier;
  const badges = element("div", "provider-badges");
  cardBadges(resource).forEach(([text, className]) => {
    badges.append(element("span", className, text));
  });
  card.append(
    tier,
    element("div", "feature-provider", `${resource.provider} · ${kindLabel(resource.kind)}`),
    element("div", "feature-amount", actionQuota(resource)),
    element("div", "feature-description", benefitSummary(resource)),
    badges,
  );
  const steps = usageSteps(resource);
  if (steps.length) {
    card.append(
      element("span", "feature-how-label", "怎么领"),
      element("p", "feature-how", steps.slice(0, 3).map((step) => step.replace(/[。；]$/, "")).join(" → ")),
    );
  }
  card.append(element("span", "feature-action", `${guide(resource).action_label || "查看操作指南"} →`));
  activateCard(card, () => showOffer(resource));
  return card;
}

function chooseFeatured(resources) {
  const choices = [];
  ["Modal", "Cloudflare", "Kaggle"].forEach((provider) => {
    const match = resources.find((resource) =>
      resource.provider === provider && resource.kind !== "grant"
    );
    if (match) choices.push(match);
  });
  resources
    .filter((resource) => ["A", "B"].includes(resource.priority_tier))
    .forEach((resource) => {
      if (choices.length < 3 && !choices.some((item) => item.provider === resource.provider)) {
        choices.push(resource);
      }
    });
  return choices.slice(0, 3);
}

function renderFeatured(resources) {
  const featured = chooseFeatured(resources);
  if (!featured.length) {
    featuredRoot.replaceChildren(element("div", "radar-empty", "还没有可推荐的官方免费资源。"));
    if (!["token-prices", "gpu-prices"].includes(currentView)) {
      heroPickTitle.textContent = "等待官方核验";
      heroPickNote.textContent = "完成刷新后会自动挑选";
    }
    return;
  }
  featuredRoot.replaceChildren(
    ...featured.map((resource, index) => featureCard(resource, index === 0)),
  );
  if (!["token-prices", "gpu-prices"].includes(currentView)) {
    heroPickTitle.textContent = `${featured[0].provider} · ${actionQuota(featured[0])}`;
    heroPickNote.textContent = guide(featured[0]).best_for || "无需信用卡 · 官方已核验";
  }
}

function renderSummary(summary, officialResources) {
  const gpuProviders = new Set(
    officialResources
      .filter((resource) => resource.kind === "gpu")
      .map((resource) => resource.provider),
  );
  summaryRoot.replaceChildren(
    metric("官方免费资源", String(officialResources.length), "已核验"),
    metric("纯免费推荐", String(summary.counts.tier_a), "A 级"),
    metric("免费 GPU 来源", String(gpuProviders.size), "官方来源"),
    metric("待处理提醒", String(summary.notifications.unread), summary.notifications.unread ? "请查看" : "暂无"),
  );

  const sources = summary.sources || {};
  const fresh = sources.fresh ?? sources.healthy ?? 0;
  const overdue = sources.overdue || 0;
  const stale = sources.stale || 0;
  const pending = sources.verification_pending || 0;
  const failed = sources.failed || 0;
  const never = sources.never || 0;
  const issueCount = overdue + stale + pending + failed + never;
  const oldestOfficial = sources.oldest_official_verified_at || summary.last_refresh_at;
  lastVerified.textContent = oldestOfficial
    ? `${formatTime(oldestOfficial)} 最旧官方核验`
    : "尚未完成官方核验";
  sourceHealth.querySelector("span:last-child").textContent =
    `${fresh}/${sources.total || 0} 来源新鲜`;
  sourceHealth.classList.toggle("unhealthy", issueCount > 0);
  const healthPercent = sources.total
    ? (fresh / sources.total) * 100
    : 0;
  sourceHealthBar.style.width = `${healthPercent}%`;
  healthySourceCount.textContent = `${fresh} 个新鲜`;
  const issueLabels = [
    overdue ? `${overdue} 个逾期` : "",
    stale ? `${stale} 个过期` : "",
    pending ? `${pending} 个待核验` : "",
    failed ? `${failed} 个失败` : "",
    never ? `${never} 个未运行` : "",
  ].filter(Boolean);
  failedSourceCount.textContent = issueLabels.join(" · ") || "全部正常";
}

function importantChanges(changes) {
  return changes.filter((change) =>
    ["high", "critical"].includes(change.importance)
    || (
      ["A", "B"].includes(change.priority_tier)
      && ["removed", "quota_changed", "limits_changed", "expiring"].includes(change.change_type)
    )
  );
}

function changeLabel(changeType) {
  return {
    added: "新增",
    updated: "信息更新",
    quota_changed: "额度变化",
    limits_changed: "限制变化",
    removed: "已下架",
    expiring: "即将到期",
  }[changeType] || changeType;
}

function renderChangePreview(changes) {
  const important = importantChanges(changes).slice(0, 2);
  if (!important.length) {
    const row = element("div", "mini-change");
    const copy = element("div");
    copy.append(
      element("strong", "", "暂无重要变化"),
      element("small", "", "社区新线索不会触发系统提醒"),
    );
    row.append(copy, element("span", "change-tag", "已同步"));
    changePreview.replaceChildren(row);
    return;
  }
  changePreview.replaceChildren(...important.map((change) => {
    const row = element("div", "mini-change");
    const copy = element("div");
    copy.append(
      element("strong", "", `${change.provider || "未知来源"} · ${changeLabel(change.change_type)}`),
      element("small", "", change.title || change.offer_id),
    );
    row.append(copy, element("span", "change-tag", change.priority_tier || "变化"));
    return row;
  }));
}

async function loadDashboard() {
  try {
    const [summary, officialPayload, changesPayload] = await Promise.all([
      fetchJson("/api/ai-resources/summary"),
      fetchJson("/api/ai-resources?verified=true&limit=200"),
      fetchJson("/api/ai-resources/changes?days=30&limit=200"),
    ]);
    renderSummary(summary, officialPayload.resources);
    renderFeatured(officialPayload.resources);
    renderChangePreview(changesPayload.changes);
  } catch {
    summaryRoot.replaceChildren(metric("资源雷达", "暂不可用", "本地数据库尚未准备好"));
    featuredRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取推荐资源。"));
    sourceHealth.classList.add("unhealthy");
    sourceHealth.querySelector("span:last-child").textContent = "来源状态不可用";
  }
}

function mainlandValues() {
  const values = [];
  if (mainlandSupported.checked) values.push("supported");
  if (mainlandUnknown.checked) values.push("unknown");
  if (mainlandUnsupported.checked) values.push("unsupported");
  return values;
}

function resourceQuery() {
  const parameters = new URLSearchParams({ limit: "200" });
  if (currentView !== "recommended") parameters.set("kind", currentView);
  if (verifiedOnly.checked) parameters.set("verified", "true");
  if (noCard.checked) parameters.set("no_card", "true");
  if (freeImageGeneration.checked) parameters.set("free_image_generation", "true");
  const mainland = mainlandValues();
  if (mainland.length) parameters.set("mainland", mainland.join(","));
  if (queryInput.value.trim()) parameters.set("q", queryInput.value.trim());
  return parameters.toString();
}

function groupResources(resources) {
  const groups = new Map();
  resources.forEach((resource) => {
    if (!groups.has(resource.provider)) groups.set(resource.provider, []);
    groups.get(resource.provider).push(resource);
  });
  return [...groups.values()];
}

function providerRow(resources) {
  const representative = resources[0];
  const row = element("article", "provider-row");
  const title = element("div", "provider-title");
  const copy = element("div");
  copy.append(
    element("strong", "", representative.provider),
    element("small", "", resources.length > 1
      ? `${resources.length} 个免费模型 · 共享同一免费政策`
      : `${kindLabel(representative.kind)} · ${representative.title}`),
  );
  title.append(element("span", "provider-icon", providerInitials(representative.provider)), copy);

  const quota = element("div", "provider-quota");
  quota.append(
    element("strong", "", actionQuota(representative)),
    element("small", "", benefitSummary(representative)),
  );
  const guideAction = element("div", "provider-guide-action");
  const steps = usageSteps(representative);
  guideAction.append(
    element("small", "", steps.length ? `${steps.length} 步开始使用` : "查看领取条件"),
    element("strong", "", "操作指南 →"),
  );
  row.append(title, quota, guideAction);
  activateCard(row, () => resources.length === 1
    ? showOffer(representative)
    : showProvider(resources));
  return row;
}

async function loadResources() {
  resultsRoot.replaceChildren(element("div", "radar-empty", "正在筛选本地资源…"));
  try {
    const payload = await fetchJson(`/api/ai-resources?${resourceQuery()}`);
    if (!payload.resources.length) {
      resultsRoot.replaceChildren(
        element("div", "radar-empty", "当前条件下没有资源，可以打开“更多筛选”放宽条件。"),
      );
      catalogCaption.textContent = "当前条件下没有匹配结果";
      return;
    }
    const groups = groupResources(payload.resources);
    catalogCaption.textContent =
      `${payload.resources.length} 项资源，已聚合为 ${groups.length} 个供应商`;
    resultsRoot.replaceChildren(...groups.map(providerRow));
  } catch {
    resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 AI 资源库。"));
  }
}

function formatUsd(value) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  const digits = number >= 10 ? 2 : number >= 1 ? 3 : number >= 0.01 ? 4 : 6;
  return `$${number.toLocaleString("zh-CN", { maximumFractionDigits: digits })}`;
}

function formatContext(value) {
  if (!value) return "未记录";
  if (value >= 1_000_000) return `${compactNumber(value / 1_000_000)}M`;
  if (value >= 1_000) return `${compactNumber(value / 1_000)}K`;
  return compactNumber(value);
}

function replaceSelectOptions(select, values, allLabel) {
  const selected = select.value;
  select.replaceChildren(new Option(allLabel, ""));
  values.forEach((value) => select.append(new Option(value, value)));
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

function priceCell(label, value, note, className = "") {
  const cell = element("div", `price-cell ${className}`.trim());
  cell.dataset.label = label;
  cell.append(element("strong", "", value));
  if (note) cell.append(element("small", "", note));
  return cell;
}

function priceVerification(item) {
  const box = element("div", "price-source");
  const badge = element("span", item.verification_level === "community" ? "baseline" : "official", item.verification_label);
  box.append(badge, element("small", "", formatTime(item.verified_at)));
  const link = safeLink("价格来源 ↗", item.pricing_url, "price-source-link");
  if (link) box.append(link);
  return box;
}

function updateCompareBar() {
  const count = comparedPrices.size;
  priceCompareBar.hidden = count === 0;
  priceCompareCount.textContent = `已选择 ${count} 项${count < 2 ? "，再选一项即可对比" : ""}`;
  openPriceCompare.disabled = count < 2;
}

function compareToggle(item, kind) {
  const label = element("label", "price-compare-toggle");
  const checkbox = element("input");
  checkbox.type = "checkbox";
  checkbox.checked = comparedPrices.has(item.price_id);
  checkbox.setAttribute("aria-label", `将 ${item.model || item.title} 加入对比`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked && comparedPrices.size >= 5) {
      checkbox.checked = false;
      refreshState.hidden = false;
      refreshState.textContent = "一次最多对比 5 项价格。";
      return;
    }
    if (checkbox.checked) comparedPrices.set(item.price_id, { ...item, price_kind: kind });
    else comparedPrices.delete(item.price_id);
    updateCompareBar();
  });
  label.append(checkbox, element("span", "", "对比"));
  return label;
}

function tokenPriceRow(item, index) {
  const row = element("article", "price-row token-price-row");
  const identity = element("div", "price-identity");
  identity.append(
    element("span", "price-rank", String(index + 1)),
    element("div", "", undefined),
  );
  identity.lastElementChild.append(
    element("strong", "", item.model),
    element("small", "", `${item.provider}${item.model_id ? ` · ${item.model_id}` : ""}`),
  );
  row.append(
    identity,
    priceCell("输入", formatUsd(item.input_per_mtok), "/ 百万 Token"),
    priceCell("输出", formatUsd(item.output_per_mtok), "/ 百万 Token"),
    priceCell("典型对话", formatUsd(item.typical_cost), "1M 输入 + 250K 输出", "highlight"),
    priceCell("上下文", formatContext(item.context_window), "Token"),
    priceVerification(item),
    compareToggle(item, "token"),
  );
  return row;
}

function gpuPriceRow(item, index, hours) {
  const row = element("article", "price-row gpu-price-row");
  const identity = element("div", "price-identity");
  identity.append(
    element("span", "price-rank", String(index + 1)),
    element("div", "", undefined),
  );
  identity.lastElementChild.append(
    element("strong", "", item.gpu_model),
    element("small", "", `${item.provider} · ${item.market_tier}`),
  );
  const hourly = item.hourly_usd === null ? "实时市场价" : formatUsd(item.hourly_usd);
  row.append(
    identity,
    priceCell("显存", item.vram_gb ? `${compactNumber(item.vram_gb)} GB` : "多种型号", item.billing_mode),
    priceCell("每 GPU 小时", hourly, item.hourly_usd === null ? "随供需变化" : "标准化 USD", "highlight"),
    priceCell(`${hours} 小时`, formatUsd(item.estimated_cost), "预估计算费"),
    priceCell("显存性价比", formatUsd(item.usd_per_vram_gb_hour), "/ GB·小时"),
    priceVerification(item),
    compareToggle(item, "gpu"),
  );
  return row;
}

function pricingIntro(title, text, tag) {
  const intro = element("div", "pricing-intro");
  const copy = element("div");
  copy.append(element("strong", "", title), element("p", "", text));
  intro.append(copy, element("span", "", tag));
  return intro;
}

function priceTable(headers, rows, className) {
  const table = element("div", `price-table ${className}`);
  const head = element("div", "price-table-head");
  headers.forEach((header) => {
    const [label, sortValue] = Array.isArray(header) ? header : [header, null];
    if (!sortValue) {
      head.append(element("span", "", label));
      return;
    }
    const button = element("button", pricingSort.value === sortValue ? "active" : "", label);
    button.type = "button";
    if (pricingSort.value === sortValue) {
      button.append(document.createTextNode(pricingDirection.value === "desc" ? " ↓" : " ↑"));
    }
    button.addEventListener("click", () => {
      if (pricingSort.value === sortValue) {
        pricingDirection.value = pricingDirection.value === "asc" ? "desc" : "asc";
      } else {
        pricingSort.value = sortValue;
        pricingDirection.value = sortValue === "context" || sortValue === "vram" ? "desc" : "asc";
      }
      loadCurrentView();
    });
    head.append(button);
  });
  table.append(head, ...rows);
  return table;
}

function renderPricingFilterSummary(total, filters) {
  pricingFilterSummary.replaceChildren();
  const count = element("strong", "", `${total} 条结果`);
  pricingFilterSummary.append(count);
  filters.filter(Boolean).forEach((filter) => {
    pricingFilterSummary.append(element("span", "", filter));
  });
  if (!filters.some(Boolean)) pricingFilterSummary.append(element("small", "", "当前未添加额外筛选"));
}

async function loadTokenPrices() {
  resultsRoot.replaceChildren(element("div", "radar-empty", "正在计算 Token 价格榜…"));
  const parameters = new URLSearchParams({
    limit: "300",
    sort: pricingSort.value || "typical",
    direction: pricingDirection.value || "asc",
    verification: tokenVerification.value,
    cache: tokenCache.value,
  });
  if (queryInput.value.trim()) parameters.set("q", queryInput.value.trim());
  if (pricingProvider.value) parameters.set("provider", pricingProvider.value);
  if (tokenMinContext.value) parameters.set("min_context", tokenMinContext.value);
  if (tokenMaxTypical.value) parameters.set("max_typical", tokenMaxTypical.value);
  if (tokenMaxInput.value) parameters.set("max_input", tokenMaxInput.value);
  if (tokenMaxOutput.value) parameters.set("max_output", tokenMaxOutput.value);
  try {
    const payload = await fetchJson(`/api/ai-prices/token?${parameters}`);
    if (pricingProvider.options.length === 1) {
      replaceSelectOptions(pricingProvider, payload.providers, "全部供应商");
    }
    catalogCaption.textContent = `${payload.total} 个有标准文本价格的模型`;
    renderPricingFilterSummary(payload.total, [
      pricingProvider.value && `供应商：${pricingProvider.value}`,
      tokenVerification.value !== "all" && tokenVerification.options[tokenVerification.selectedIndex].text,
      tokenMinContext.value && `上下文 ≥ ${tokenMinContext.options[tokenMinContext.selectedIndex].text.replace("+", "")}`,
      tokenMaxTypical.value && `典型成本 ≤ $${tokenMaxTypical.value}`,
      tokenMaxInput.value && `输入 ≤ $${tokenMaxInput.value}`,
      tokenMaxOutput.value && `输出 ≤ $${tokenMaxOutput.value}`,
      tokenCache.value !== "any" && tokenCache.options[tokenCache.selectedIndex].text,
    ]);
    if (!payload.prices.length) {
      resultsRoot.replaceChildren(element("div", "radar-empty", "当前条件下没有 Token 价格。"));
      return;
    }
    const rows = payload.prices.map(tokenPriceRow);
    resultsRoot.replaceChildren(
      pricingIntro(
        "默认按典型对话成本排序",
        "统一假设 100 万输入 Token + 25 万输出 Token；输入、输出原价始终单独展示。",
        "透明公式",
      ),
      priceTable(
        [["模型 / 供应商", "provider"], ["输入", "input"], ["输出", "output"], ["典型对话", "typical"], ["上下文", "context"], "核验", ""],
        rows,
        "token-table",
      ),
    );
  } catch {
    resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 Token 价格榜。"));
  }
}

async function loadGpuPrices() {
  resultsRoot.replaceChildren(element("div", "radar-empty", "正在计算 GPU 算力榜…"));
  const hours = Number(gpuHours.value || 10);
  const parameters = new URLSearchParams({
    limit: "300",
    sort: pricingSort.value || "hourly",
    direction: pricingDirection.value || "asc",
    hours: String(hours),
    price_mode: gpuPriceMode.value,
  });
  if (queryInput.value.trim()) parameters.set("q", queryInput.value.trim());
  if (pricingProvider.value) parameters.set("provider", pricingProvider.value);
  if (gpuModel.value) parameters.set("gpu", gpuModel.value);
  if (gpuMinVram.value) parameters.set("min_vram", gpuMinVram.value);
  if (gpuMaxHourly.value) parameters.set("max_hourly", gpuMaxHourly.value);
  if (gpuBilling.value) parameters.set("billing", gpuBilling.value);
  if (gpuTier.value) parameters.set("tier", gpuTier.value);
  try {
    const payload = await fetchJson(`/api/ai-prices/gpu?${parameters}`);
    if (pricingProvider.options.length === 1) {
      replaceSelectOptions(pricingProvider, payload.providers, "全部供应商");
    }
    if (gpuModel.options.length === 1) {
      replaceSelectOptions(gpuModel, payload.gpu_models, "全部型号");
    }
    if (gpuBilling.options.length === 1) {
      replaceSelectOptions(gpuBilling, payload.billing_modes, "全部模式");
    }
    if (gpuTier.options.length === 1) {
      replaceSelectOptions(gpuTier, payload.market_tiers, "全部层级");
    }
    catalogCaption.textContent = `${payload.total} 条 GPU 官方价格，按单 GPU 口径比较`;
    renderPricingFilterSummary(payload.total, [
      pricingProvider.value && `供应商：${pricingProvider.value}`,
      gpuModel.value && `型号：${gpuModel.value}`,
      gpuMinVram.value && `显存 ≥ ${gpuMinVram.value} GB`,
      gpuMaxHourly.value && `小时价 ≤ $${gpuMaxHourly.value}`,
      gpuBilling.value && `计费：${gpuBilling.value}`,
      gpuTier.value && `层级：${gpuTier.value}`,
      gpuPriceMode.value !== "all" && gpuPriceMode.options[gpuPriceMode.selectedIndex].text,
    ]);
    if (!payload.prices.length) {
      resultsRoot.replaceChildren(element("div", "radar-empty", "当前条件下没有 GPU 价格。"));
      return;
    }
    const rows = payload.prices.map((item, index) => gpuPriceRow(item, index, hours));
    resultsRoot.replaceChildren(
      pricingIntro(
        "同型号、同计费模式下再比较",
        `小时价统一换算成单 GPU USD；当前任务成本按 ${hours} 小时估算，不包含存储、流量和税费。`,
        "官方价格",
      ),
      priceTable(
        [["GPU / 供应商", "provider"], ["显存", "vram"], ["每小时", "hourly"], [`${hours} 小时`, "hourly"], ["显存性价比", "memory_value"], "核验", ""],
        rows,
        "gpu-table",
      ),
    );
  } catch {
    resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 GPU 价格榜。"));
  }
}

function configurePricingControls() {
  const tokenPrices = currentView === "token-prices";
  if (pricingControls.dataset.view !== currentView) {
    pricingControls.dataset.view = currentView;
    pricingSort.replaceChildren();
    const options = tokenPrices
      ? [["typical", "典型对话成本"], ["input", "输入价格"], ["output", "输出价格"], ["context", "上下文长度"], ["provider", "供应商"]]
      : [["hourly", "每小时价格"], ["memory_value", "显存性价比"], ["vram", "显存大小"], ["provider", "供应商"]];
    options.forEach(([value, label]) => pricingSort.append(new Option(label, value)));
    replaceSelectOptions(pricingProvider, [], "全部供应商");
    replaceSelectOptions(gpuModel, [], "全部型号");
    replaceSelectOptions(gpuBilling, [], "全部模式");
    replaceSelectOptions(gpuTier, [], "全部层级");
    pricingDirection.value = "asc";
    comparedPrices.clear();
    updateCompareBar();
  }
  tokenPriceControls.forEach((control) => { control.hidden = !tokenPrices; });
  gpuPriceControls.forEach((control) => { control.hidden = tokenPrices; });
}

function updateHero() {
  if (currentView === "poster") {
    heroEyebrow.textContent = "AI-GENERATED DAILY POSTER";
    heroTitle.replaceChildren("每天一张，", element("br"), "AI 资源情报海报");
    heroCopy.textContent = "海报由图片模型整张生成，再由本机 OCR 核对服务商、免费额度和价格数字。校验不通过就不会发布。";
    heroPickLabel.textContent = "质量控制";
    heroPickTitle.textContent = "最多 3 次 · 严格校验";
    heroPickNote.textContent = "图片失败不会影响资源雷达和昨日海报";
  } else if (currentView === "token-prices") {
    heroEyebrow.textContent = "TOKEN PRICE LEADERBOARD";
    heroTitle.replaceChildren("Token 费用，", element("br"), "谁更便宜？");
    heroCopy.textContent = "输入、输出、缓存和上下文分别比较，再用公开公式估算典型任务成本。原价和核验级别不会被综合分隐藏。";
    heroPickLabel.textContent = "默认比较口径";
    heroPickTitle.textContent = "1M 输入 + 250K 输出";
    heroPickNote.textContent = "可切换按输入价、输出价或上下文排序";
  } else if (currentView === "gpu-prices") {
    heroEyebrow.textContent = "GPU COMPUTE LEADERBOARD";
    heroTitle.replaceChildren("同一块 GPU，", element("br"), "哪里租更省？");
    heroCopy.textContent = "统一换算成单 GPU 每小时费用，同时展示显存、计费模式和任务成本。实时市场价与固定按需价分开标识。";
    heroPickLabel.textContent = "默认比较口径";
    heroPickTitle.textContent = "单 GPU · USD / 小时";
    heroPickNote.textContent = "不包含存储、网络、税费和长期合约折扣";
  } else {
    heroEyebrow.textContent = "TODAY'S FREE AI PICKS";
    heroTitle.replaceChildren("今天有什么", element("br"), "值得白嫖？");
    heroCopy.textContent = "先看清楚具体送什么、多久恢复、有哪些门槛，再照着操作步骤直接开始用。每项政策都保留官方核验依据。";
    heroPickLabel.textContent = "今日首选";
  }
}

function posterStatusLabel(report) {
  if (!report) return "今日尚未生成";
  if (report.status === "success") return "已通过 OCR 校验";
  if (report.status === "running") return "正在生成";
  return {
    poster_disabled: "日报功能已关闭",
    poster_not_configured: "尚未配置图片 API Key",
    poster_model_not_formal_eligible: "所选模型未通过正式日报校验",
    poster_image_aspect_ratio_invalid: "图片比例不符合 3:4 海报要求",
    poster_daily_attempt_limit: "今日 3 次调用额度已用完",
    poster_validation_failed: "文字或数字校验未通过",
    poster_insufficient_free_offers: "可用数据不足",
  }[report.error_code] || "今日生成失败";
}

function posterReasonLabel(reason) {
  return {
    chinese_ocr_benchmark_failed: "中文 OCR 基准未通过",
    openai_keychain_credential_missing: "Keychain 中没有 OpenAI 凭据",
    openclaw_unavailable: "未找到 OpenClaw",
    openclaw_provider_status_unavailable: "无法读取 OpenClaw 图片供应商状态",
    openclaw_provider_zai_not_configured: "OpenClaw 尚未配置 ZAI",
    "openclaw_model_cogview-3-flash_not_configured": "OpenClaw 未启用 CogView-3-Flash",
    poster_model_unsupported: "当前运行版本不支持所选模型",
  }[reason] || reason || "无";
}

function posterMeta(publishedReport, status, todayReport) {
  const meta = element("div", "poster-meta");
  const modelProvider = publishedReport?.provider || status.provider;
  const modelName = publishedReport?.model || status.model;
  meta.append(
    element("span", todayReport?.status === "success" ? "poster-ok" : "poster-warn", posterStatusLabel(todayReport)),
    element("span", "", `${modelProvider} / ${modelName}`),
    element("span", status.enabled ? "poster-ok" : "poster-warn", status.enabled ? "日报已启用" : "日报已关闭"),
    element(
      "span",
      status.formal_poster_eligible ? "poster-ok" : "poster-warn",
      status.formal_poster_eligible ? "正式日报可用" : posterReasonLabel(status.reason),
    ),
    element("span", "", `调用 ${todayReport?.attempt_count || 0} / 3`),
    element("span", "", publishedReport?.generated_at ? formatTime(publishedReport.generated_at) : "等待生成"),
  );
  if (status.last_failure?.error_code) {
    meta.append(element("span", "poster-warn", `最近失败：${posterStatusLabel({ status: "failed", error_code: status.last_failure.error_code })}`));
  }
  return meta;
}

function posterHistoryCard(report) {
  const card = element("article", "poster-history-card");
  const heading = element("div");
  heading.append(
    element("strong", "", report.report_date),
    element("small", "", posterStatusLabel(report)),
  );
  card.append(heading);
  if (report.image_url) {
    const link = element("a", "poster-history-link");
    link.href = report.image_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.append(element("span", "", "查看海报"));
    card.append(link);
  } else {
    card.append(element("span", "poster-history-error", report.error_code || "未生成图片"));
  }
  return card;
}

async function pollPoster() {
  try {
    const status = await fetchJson("/api/ai-daily/status");
    if (status.task?.status === "running") {
      refreshState.hidden = false;
      refreshState.textContent = "图片模型正在生成并进行本地 OCR 校验…";
      window.setTimeout(pollPoster, 1500);
      return;
    }
    refreshState.hidden = false;
    refreshState.textContent = status.task?.status === "completed"
      ? "日报海报已通过校验并发布。"
      : `日报未发布：${posterStatusLabel(status.task?.report || { status: "failed", error_code: status.task?.error })}`;
    loadPoster();
  } catch {
    refreshState.hidden = false;
    refreshState.textContent = "无法读取日报生成状态。";
  }
}

async function startPoster(force) {
  refreshState.hidden = false;
  refreshState.textContent = "正在启动纯图片日报生成…";
  try {
    await fetchJson("/api/ai-daily/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });
    pollPoster();
  } catch (error) {
    refreshState.textContent = error.message === "daily_poster_already_running"
      ? "日报生成任务已经在运行。"
      : "无法启动日报生成任务。";
  }
}

async function loadPoster() {
  resultsRoot.replaceChildren(element("div", "radar-empty", "正在读取日报海报…"));
  try {
    const [latestPayload, historyPayload, status] = await Promise.all([
      fetchJson("/api/ai-daily/latest"),
      fetchJson("/api/ai-daily?days=90"),
      fetchJson("/api/ai-daily/status"),
    ]);
    const latest = latestPayload.report;
    catalogCaption.textContent = "只展示通过本机 OCR 文字和数字校验的最终图片";
    const layout = element("div", "poster-layout");
    const stage = element("section", "poster-stage");
    const stageHeading = element("div", "poster-stage-heading");
    const copy = element("div");
    copy.append(
      element("span", "poster-kicker", "LATEST VERIFIED POSTER"),
      element("h3", "", latest ? `${latest.report_date} 日报` : "等待第一张合格日报"),
    );
    const generate = element("button", "poster-generate", status.today?.status === "success" ? "重新生成" : "生成今日海报");
    generate.type = "button";
    generate.disabled = !status.enabled
      || !status.configured
      || !status.formal_poster_eligible
      || status.task?.status === "running"
      || (status.today?.attempt_count || 0) >= status.max_attempts_per_day;
    generate.title = !status.enabled
      ? "请先启用日报"
      : !status.configured
        ? posterReasonLabel(status.configuration_reason)
        : !status.formal_poster_eligible
          ? posterReasonLabel(status.reason)
          : "生成一张经过最终 WebP OCR 校验的日报";
    generate.addEventListener("click", () => startPoster(status.today?.status === "success"));
    stageHeading.append(copy, generate);
    stage.append(stageHeading, posterMeta(latest, status, status.today));
    if (latest?.image_url) {
      const frame = element("div", "poster-frame");
      const image = element("img");
      image.src = latest.image_url;
      image.alt = `${latest.report_date} AI 免费资源雷达日报`;
      image.loading = "eager";
      frame.append(image);
      const actions = element("div", "poster-actions");
      const download = element("a", "poster-download", "下载 WebP");
      download.href = latest.image_url;
      download.download = `ai-resource-radar-${latest.report_date}.webp`;
      actions.append(
        download,
        element("span", "", `${latest.image_bytes ? compactNumber(latest.image_bytes / 1024) : "—"} KB · 1080 × 1440`),
      );
      stage.append(frame, actions);
    } else {
      const empty = element("div", "poster-empty");
      let emptyTitle = "今天还没有合格海报";
      let emptyHelp = "点击生成后，图片必须通过本机 OCR 校验才会出现在这里。";
      if (!status.enabled) {
        emptyTitle = "日报功能当前已关闭";
        emptyHelp = `运行：ai-radar poster configure --provider ${status.provider} --model ${status.model} --enable`;
      } else if (!status.configured) {
        emptyTitle = `先配置 ${status.provider} / ${status.model}`;
        emptyHelp = status.provider === "openai"
          ? "运行：ai-radar poster key set"
          : `请先在 OpenClaw 配置图片供应商：${posterReasonLabel(status.configuration_reason)}`;
      } else if (!status.formal_poster_eligible) {
        emptyTitle = "当前模型只能用于生图测试";
        emptyHelp = `正式日报已在调用 API 前拦截：${posterReasonLabel(status.reason)}`;
      }
      empty.append(
        element("strong", "", emptyTitle),
        element("p", "", emptyHelp),
      );
      stage.append(empty);
    }

    const history = element("aside", "poster-history");
    history.append(
      element("span", "poster-kicker", "90 DAY HISTORY"),
      element("h3", "", "生成记录"),
      element("p", "", "失败候选图片会立即删除，只保留状态与错误代码。"),
    );
    const historyList = element("div", "poster-history-list");
    if (historyPayload.reports.length) {
      historyList.append(...historyPayload.reports.map(posterHistoryCard));
    } else {
      historyList.append(element("div", "mini-empty", "暂无日报记录"));
    }
    history.append(historyList);
    layout.append(stage, history);
    resultsRoot.replaceChildren(layout);
  } catch {
    resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取日报海报。"));
  }
}

async function loadChanges() {
  resultsRoot.replaceChildren(element("div", "radar-empty", "正在读取变化记录…"));
  try {
    const payload = await fetchJson("/api/ai-resources/changes?days=30&limit=200");
    if (!payload.changes.length) {
      resultsRoot.replaceChildren(element("div", "radar-empty", "最近 30 天还没有变化记录。"));
      return;
    }
    const rows = payload.changes.map((change) => {
      const row = element("article", "change-row");
      row.append(
        element("time", "", formatTime(change.detected_at)),
        element("span", "", changeLabel(change.change_type)),
        element("strong", "", `${change.provider || "未知来源"} · ${change.title || change.offer_id}`),
      );
      return row;
    });
    catalogCaption.textContent = `最近 30 天的 ${payload.changes.length} 条记录`;
    resultsRoot.replaceChildren(...rows);
  } catch {
    resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取变化记录。"));
  }
}

function loadCurrentView() {
  tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === currentView);
  });
  const changes = currentView === "changes";
  const poster = currentView === "poster";
  const priceView = ["token-prices", "gpu-prices"].includes(currentView);
  updateHero();
  featuredSection.hidden = currentView !== "recommended";
  summaryRoot.hidden = priceView || changes || poster;
  pricingControls.hidden = !priceView;
  browserGrid.classList.toggle("pricing-mode", priceView || poster);
  radarSidebar.hidden = priceView || poster;
  filters.hidden = changes || priceView || poster || filterToggle.getAttribute("aria-expanded") !== "true";
  filterToggle.hidden = changes || priceView || poster;
  queryInput.disabled = changes || poster;
  catalogTitle.textContent = currentView === "token-prices"
    ? "Token 费用榜单"
    : currentView === "gpu-prices"
      ? "GPU 算力费用榜单"
      : poster
        ? "日报海报"
      : changes
        ? "变化记录"
        : currentView === "recommended"
          ? "按用途浏览"
          : `${kindLabel(currentView)}资源`;
  if (priceView) configurePricingControls();
  if (poster) loadPoster();
  else if (changes) loadChanges();
  else if (currentView === "token-prices") loadTokenPrices();
  else if (currentView === "gpu-prices") loadGpuPrices();
  else loadResources();
}

function selectView(view) {
  if (!knownViews.has(view)) return;
  currentView = view;
  window.history.replaceState(null, "", view === "recommended" ? "#" : `#${view}`);
  loadCurrentView();
  if (view !== "recommended") {
    document.querySelector(".catalog-section").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function pollRefresh() {
  try {
    const state = await fetchJson("/api/ai-resources/refresh");
    refreshState.hidden = false;
    if (state.status === "running") {
      refreshState.textContent = `正在核验官方来源 · 开始于 ${formatTime(state.started_at)}`;
      refreshTimer = window.setTimeout(pollRefresh, 1200);
      return;
    }
    refreshButton.disabled = false;
    refreshState.textContent = state.status === "completed"
      ? "核验完成，资源列表和变化记录已更新。"
      : state.status === "partial"
        ? "核验完成，但部分来源需要稍后重试或人工复核。"
        : "核验任务未能完成，请查看来源状态。";
    await Promise.all([loadDashboard(), loadCurrentView()]);
  } catch {
    refreshButton.disabled = false;
    refreshState.hidden = false;
    refreshState.textContent = "无法读取刷新状态。";
  }
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  refreshState.hidden = false;
  refreshState.textContent = "正在启动核验任务…";
  try {
    await fetchJson("/api/ai-resources/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true }),
    });
    pollRefresh();
  } catch (error) {
    refreshButton.disabled = false;
    refreshState.textContent = error.message === "ai_radar_refresh_already_running"
      ? "已有核验任务在运行。"
      : "无法启动核验任务。";
  }
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => selectView(tab.dataset.view));
});

[verifiedOnly, noCard, freeImageGeneration, mainlandSupported, mainlandUnknown, mainlandUnsupported]
  .forEach((control) => control.addEventListener("change", loadCurrentView));

queryInput.addEventListener("input", () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(loadCurrentView, 250);
});

[pricingSort, pricingDirection, pricingProvider, tokenVerification, tokenMinContext,
  tokenMaxTypical, tokenMaxInput, tokenMaxOutput, tokenCache, gpuModel, gpuMinVram,
  gpuMaxHourly, gpuBilling, gpuTier, gpuPriceMode, gpuHours]
  .forEach((control) => control.addEventListener("change", loadCurrentView));

document.querySelector("#reset-pricing-filters").addEventListener("click", () => {
  queryInput.value = "";
  pricingProvider.value = "";
  pricingDirection.value = "asc";
  tokenVerification.value = "all";
  tokenMinContext.value = "";
  tokenMaxTypical.value = "";
  tokenMaxInput.value = "";
  tokenMaxOutput.value = "";
  tokenCache.value = "any";
  gpuModel.value = "";
  gpuMinVram.value = "";
  gpuMaxHourly.value = "";
  gpuBilling.value = "";
  gpuTier.value = "";
  gpuPriceMode.value = "all";
  gpuHours.value = "10";
  pricingSort.value = currentView === "token-prices" ? "typical" : "hourly";
  loadCurrentView();
});

filterToggle.addEventListener("click", () => {
  const expanded = filterToggle.getAttribute("aria-expanded") === "true";
  filterToggle.setAttribute("aria-expanded", String(!expanded));
  filters.hidden = expanded;
});

document.querySelector("#show-all-resources").addEventListener("click", () => {
  verifiedOnly.checked = false;
  noCard.checked = false;
  freeImageGeneration.checked = false;
  mainlandSupported.checked = true;
  mainlandUnknown.checked = true;
  mainlandUnsupported.checked = true;
  filterToggle.setAttribute("aria-expanded", "true");
  filters.hidden = false;
  selectView("recommended");
});

document.querySelector("#ranking-explainer").addEventListener("click", () => {
  detailRoot.replaceChildren(
    element("h2", "", "推荐规则"),
    element("p", "", "页面不使用隐藏总分。A 级优先表示官方核验、无需信用卡、周期免费，并且中国大陆未被官方明确排除。"),
  );
  const box = element("div", "evidence-box");
  [
    "A：官方核验、无需信用卡、周期免费",
    "B：官方核验且无需信用卡，但额度浮动或有资格条件",
    "C：需要申请、信用卡、特定地区或一次性试用",
    "D：社区发现，尚未官方核验",
  ].forEach((rule) => box.append(element("p", "", rule)));
  detailRoot.append(box);
  openDialog();
});

document.querySelector("#pricing-method").addEventListener("click", () => {
  detailRoot.replaceChildren(
    element("h2", "", "价格榜比较口径"),
    element("p", "offer-provider", "榜单只使用公开字段和明确公式，不生成隐藏综合分。"),
  );
  const sections = [
    ["Token", "输入和输出均按美元/百万 Token 展示。典型对话成本 = 100 万输入价格 + 25 万输出价格；缓存费用单独保留，不混入默认公式。"],
    ["GPU", "固定价统一换算为单 GPU 每小时美元价格；任务成本 = 小时价 × 选择的运行时长。显存性价比仅表示美元/GB·小时，不代表训练速度。"],
    ["核验", "官方页面解析结果标为“官方价格”；genai-prices 等成熟目录只标为“社区价格基线”，不会冒充官方核验。"],
    ["未包含", "存储、网络流量、税费、区域差价、批量折扣和预留合约可能改变最终账单，使用前应再次打开价格来源确认。"],
  ];
  sections.forEach(([title, copy]) => {
    const box = element("section", "policy-note");
    box.append(element("strong", "", title), element("p", "", copy));
    detailRoot.append(box);
  });
  openDialog();
});

document.querySelector("#clear-price-compare").addEventListener("click", () => {
  comparedPrices.clear();
  updateCompareBar();
  loadCurrentView();
});

openPriceCompare.addEventListener("click", () => {
  const items = [...comparedPrices.values()];
  if (items.length < 2) return;
  detailRoot.replaceChildren(
    element("h2", "", items[0].price_kind === "token" ? "Token 价格对比" : "GPU 费用对比"),
    element("p", "offer-provider", `${items.length} 项并排比较；价格来源和核验时间保留。`),
  );
  const grid = element("div", "price-comparison-grid");
  items.forEach((item) => {
    const card = element("article", "price-comparison-card");
    if (item.price_kind === "token") {
      card.append(
        element("span", "compare-provider", item.provider),
        element("h3", "", item.model),
        priceCell("输入 / 百万", formatUsd(item.input_per_mtok)),
        priceCell("输出 / 百万", formatUsd(item.output_per_mtok)),
        priceCell("典型对话", formatUsd(item.typical_cost), "1M 输入 + 250K 输出", "highlight"),
        priceCell("上下文", formatContext(item.context_window)),
      );
    } else {
      card.append(
        element("span", "compare-provider", item.provider),
        element("h3", "", item.gpu_model),
        priceCell("每 GPU 小时", item.hourly_usd === null ? "实时市场价" : formatUsd(item.hourly_usd), item.market_tier, "highlight"),
        priceCell("显存", item.vram_gb ? `${compactNumber(item.vram_gb)} GB` : "多种型号"),
        priceCell("任务预估", formatUsd(item.estimated_cost), `${gpuHours.value} 小时`),
      );
    }
    const link = safeLink("查看价格来源 ↗", item.pricing_url, "price-source-link");
    if (link) card.append(link);
    grid.append(card);
  });
  detailRoot.append(grid);
  openDialog();
});

closeDialogButton.addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

Promise.all([loadDashboard(), loadCurrentView()]);
