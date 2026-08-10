/* Static, read-only public entry point backed only by exported JSON files. */
import { createOfferCard } from "./shared/cards.js";
import { element, safeLink } from "./shared/dom.js";
import {
  formatTime,
  formatUsd,
  textValue,
  verificationLabel,
} from "./shared/formatters.js";

const DATA = {
  manifest: "data/manifest.json",
  summary: "data/summary.json",
  sources: "data/source-health.json",
  resources: "data/resources.json",
  tokenPrices: "data/token-prices.json",
  gpuPrices: "data/gpu-prices.json",
  changes: "data/changes.json",
};
const PAGE_SIZE = 20;
const RESOURCE_VIEWS = new Set(["recommended", "token", "gpu", "grant"]);
const PRICE_VIEWS = new Set(["token-prices", "gpu-prices"]);
const KNOWN_VIEWS = new Set([...RESOURCE_VIEWS, ...PRICE_VIEWS]);
const IMPORTANT_CHANGES = new Set(["removed", "quota_changed", "limits_changed", "expiring"]);

const COPY = {
  "zh-CN": {
    "health.loading": "读取来源状态", "health.title": "来源核验状态",
    "nav.free": "免费资源", "nav.prices": "价格榜单",
    "view.recommended": "全部精选", "view.token": "免费 Token", "view.gpu": "免费 GPU",
    "view.grant": "资助活动", "view.tokenPrices": "Token 价格", "view.gpuPrices": "GPU 价格",
    "hero.eyebrow": "VERIFIED FREE AI · UPDATED DAILY", "hero.title": "今天有哪些真正能领的免费 AI 资源？",
    "hero.description": "额度、门槛、领取步骤和官方证据一次看清。", "hero.updated": "数据核验时间",
    "featured.kicker": "TODAY'S PICKS", "featured.title": "今天最值得领", "featured.note": "不同供应商 · 无需信用卡优先",
    "changes.kicker": "VERIFIED CHANGES", "changes.title": "最近重要变化",
    "catalog.kicker": "CATALOGUE", "catalog.title": "完整资源目录", "catalog.caption": "按供应商、核验、信用卡和大陆状态筛选。",
    "download.json": "下载 JSON", "download.csv": "下载 CSV", "filters.search": "搜索",
    "filters.searchPlaceholder": "供应商、模型或关键词", "filters.provider": "供应商", "filters.allProviders": "全部供应商",
    "filters.verification": "核验", "filters.all": "全部", "filters.official": "仅官方", "filters.community": "社区或待核验",
    "filters.card": "信用卡", "filters.noCard": "无需信用卡", "filters.cardRequired": "需要或待确认",
    "filters.mainland": "大陆状态", "filters.supported": "可用", "filters.unknown": "待确认", "filters.unsupported": "不支持",
    "filters.sort": "排序", "filters.clear": "清除筛选", "sort.recommended": "推荐度", "sort.updated": "更新时间",
    "sort.price": "价格从低", "sort.provider": "供应商", "status.loading": "正在读取公开数据…",
    "pager.previous": "上一页", "pager.next": "下一页", "footer.readOnly": "公开只读目录，不会代你注册、提交或读取账号。",
    "footer.changes": "变化数据", "footer.health": "来源健康", "footer.github": "GitHub 源码",
    freeCount: "免费资源", priceCount: "价格条目", sourceCount: "新鲜来源", imageCount: "免费生图",
    loaded: "显示", noData: "当前条件下没有结果。", page: "第 {page} / {pages} 页", healthFresh: "来源新鲜",
    healthPartial: "部分来源需复核", fresh: "新鲜", overdue: "逾期", failed: "失败", pending: "待复核", stale: "陈旧", never: "未采集",
    input: "输入 / 百万", output: "输出 / 百万", typical: "典型成本", gpu: "GPU", hourly: "每小时", vram: "显存",
    source: "价格来源", updated: "核验", changeAdded: "新增", changeRemoved: "下架", changeQuota: "额度变化", changeLimits: "限制变化", changeExpiring: "即将到期",
    priceHeroTitle: "Token 和 GPU 算力，哪里更便宜？", priceHeroDescription: "统一价格单位，保留核验级别和官方来源，不用隐藏总分。",
    priceCatalogTitle: "完整价格榜单", priceCatalogCaption: "按供应商、核心价格和核验时间比较。",
  },
  en: {
    "health.loading": "Loading source status", "health.title": "Source verification",
    "nav.free": "Free resources", "nav.prices": "Price rankings",
    "view.recommended": "Recommended", "view.token": "Free tokens", "view.gpu": "Free GPU",
    "view.grant": "Grants", "view.tokenPrices": "Token prices", "view.gpuPrices": "GPU prices",
    "hero.eyebrow": "VERIFIED FREE AI · UPDATED DAILY", "hero.title": "Which AI resources can you actually claim today?",
    "hero.description": "See the quota, requirements, claim steps, and official evidence together.", "hero.updated": "Data verified",
    "featured.kicker": "TODAY'S PICKS", "featured.title": "Best resources to claim", "featured.note": "Different providers · no-card first",
    "changes.kicker": "VERIFIED CHANGES", "changes.title": "Important recent changes",
    "catalog.kicker": "CATALOGUE", "catalog.title": "Complete resource directory", "catalog.caption": "Filter by provider, verification, card, and mainland availability.",
    "download.json": "Download JSON", "download.csv": "Download CSV", "filters.search": "Search",
    "filters.searchPlaceholder": "Provider, model, or keyword", "filters.provider": "Provider", "filters.allProviders": "All providers",
    "filters.verification": "Verification", "filters.all": "All", "filters.official": "Official only", "filters.community": "Community or pending",
    "filters.card": "Card", "filters.noCard": "No card", "filters.cardRequired": "Required or unknown",
    "filters.mainland": "Mainland", "filters.supported": "Supported", "filters.unknown": "Unknown", "filters.unsupported": "Unavailable",
    "filters.sort": "Sort", "filters.clear": "Clear filters", "sort.recommended": "Recommended", "sort.updated": "Updated",
    "sort.price": "Lowest price", "sort.provider": "Provider", "status.loading": "Loading public data…",
    "pager.previous": "Previous", "pager.next": "Next", "footer.readOnly": "Public read-only directory. It never registers, submits, or reads accounts.",
    "footer.changes": "Change data", "footer.health": "Source health", "footer.github": "GitHub source",
    freeCount: "Free resources", priceCount: "Price rows", sourceCount: "Fresh sources", imageCount: "Free image APIs",
    loaded: "Showing", noData: "No results match these filters.", page: "Page {page} / {pages}", healthFresh: "Sources fresh",
    healthPartial: "Some sources need review", fresh: "Fresh", overdue: "Overdue", failed: "Failed", pending: "Pending", stale: "Stale", never: "Never",
    input: "Input / 1M", output: "Output / 1M", typical: "Typical cost", gpu: "GPU", hourly: "Hourly", vram: "VRAM",
    source: "Price source", updated: "Verified", changeAdded: "Added", changeRemoved: "Removed", changeQuota: "Quota changed", changeLimits: "Limits changed", changeExpiring: "Expiring",
    priceHeroTitle: "Where are AI tokens and GPU compute cheapest?", priceHeroDescription: "Compare normalized prices with verification and official sources—no opaque score.",
    priceCatalogTitle: "Complete price rankings", priceCatalogCaption: "Compare providers, core prices, and verification time.",
  },
};

const state = {
  locale: "zh-CN", group: "free", view: "recommended", page: 1,
  data: {}, rows: [], filtered: [],
};
const $ = (id) => document.getElementById(id);
const t = (key) => COPY[state.locale]?.[key] || key;
const items = (payload) => Array.isArray(payload) ? payload : Array.isArray(payload?.items) ? payload.items : [];
const priority = (row) => ({ A: 0, B: 1, C: 2, D: 3 }[row.priority_tier] ?? 4);

function formatCount(value) { return Number(value || 0).toLocaleString(state.locale); }
function groupFor(view) { return PRICE_VIEWS.has(view) ? "prices" : "free"; }
function defaultView(group) { return group === "prices" ? "token-prices" : "recommended"; }
function defaultSort() { return state.group === "prices" ? "price" : "recommended"; }
function changeLabel(value) {
  return {
    added: t("changeAdded"), removed: t("changeRemoved"), quota_changed: t("changeQuota"),
    limits_changed: t("changeLimits"), expiring: t("changeExpiring"),
  }[value] || textValue(value);
}

function readRoute() {
  const params = new URLSearchParams(location.search);
  const requested = params.get("view") || params.get("tab") || "recommended";
  state.view = KNOWN_VIEWS.has(requested) ? requested : "recommended";
  state.group = groupFor(state.view);
  state.page = Math.max(1, Number.parseInt(params.get("page") || "1", 10) || 1);
  $("search-input").value = params.get("q") || "";
  for (const [id, key] of [["provider-filter", "provider"], ["verification-filter", "verification"], ["card-filter", "card"], ["mainland-filter", "mainland"], ["sort-filter", "sort"]]) {
    const value = params.get(key);
    if (value && [...$(id).options].some((option) => option.value === value)) $(id).value = value;
  }
  if (!params.has("sort")) $("sort-filter").value = defaultSort();
}

function writeRoute() {
  const url = new URL(location.href);
  url.search = "";
  if (state.view !== "recommended") url.searchParams.set("view", state.view);
  const query = $("search-input").value.trim();
  if (query) url.searchParams.set("q", query);
  if (state.page > 1) url.searchParams.set("page", String(state.page));
  for (const [id, key, defaults] of [["provider-filter", "provider", [""]], ["verification-filter", "verification", ["all"]], ["card-filter", "card", ["all"]], ["mainland-filter", "mainland", ["all"]], ["sort-filter", "sort", [defaultSort()]]]) {
    const value = $(id).value;
    if (!defaults.includes(value)) url.searchParams.set(key, value);
  }
  history.replaceState(null, "", `${url.pathname}${url.search}`);
}

function recommendedRows(resources) {
  const seen = new Set();
  return sortRows(resources.filter((row) =>
    ["official_api", "official_page"].includes(row.verification_level)
    && ["A", "B"].includes(row.priority_tier)
    && row.requires_card === "no"
    && ["supported", "unknown"].includes(row.mainland_status)
  )).filter((row) => {
    const provider = String(row.provider || "").toLowerCase();
    if (seen.has(provider)) return false;
    seen.add(provider);
    return true;
  });
}

function currentRows() {
  if (state.view === "token-prices") return items(state.data.tokenPrices);
  if (state.view === "gpu-prices") return items(state.data.gpuPrices);
  const resources = items(state.data.resources);
  if (state.view === "recommended") return recommendedRows(resources);
  return resources.filter((row) => row.kind === state.view);
}

function sortRows(rows) {
  const mode = $("sort-filter")?.value || "recommended";
  return [...rows].sort((a, b) => {
    if (mode === "price") return Number(a.typical_cost ?? a.hourly_usd ?? Infinity) - Number(b.typical_cost ?? b.hourly_usd ?? Infinity);
    if (mode === "provider") return textValue(a.provider).localeCompare(textValue(b.provider), state.locale);
    if (mode === "updated") return textValue(b.last_changed_at || b.verified_at).localeCompare(textValue(a.last_changed_at || a.verified_at));
    return priority(a) - priority(b)
      || Number(b.mainland_status === "supported") - Number(a.mainland_status === "supported")
      || textValue(a.provider).localeCompare(textValue(b.provider), state.locale);
  });
}

function filteredRows() {
  const query = $("search-input").value.trim().toLowerCase();
  const provider = $("provider-filter").value;
  const verification = $("verification-filter").value;
  const card = $("card-filter").value;
  const mainland = $("mainland-filter").value;
  state.filtered = sortRows(currentRows().filter((row) => {
    const searchable = `${row.provider || ""} ${row.title || ""} ${row.model || ""} ${row.gpu_model || ""}`.toLowerCase();
    if (query && !searchable.includes(query)) return false;
    if (provider && row.provider !== provider) return false;
    if (state.group === "free") {
      const official = ["official_api", "official_page"].includes(row.verification_level);
      if (verification === "official" && !official) return false;
      if (verification === "community" && official) return false;
      if (card === "no" && row.requires_card !== "no") return false;
      if (card === "yes" && row.requires_card === "no") return false;
      if (mainland !== "all" && row.mainland_status !== mainland) return false;
    }
    return true;
  }));
  return state.filtered;
}

function renderSummary() {
  const root = $("summary");
  root.replaceChildren();
  const manifest = state.data.manifest || {};
  const counts = manifest.counts || {};
  const resources = items(state.data.resources);
  const metrics = [
    [t("freeCount"), counts.resources, state.locale === "en" ? "verified offers" : "已核验政策"],
    [t("priceCount"), Number(counts.token_prices || 0) + Number(counts.gpu_prices || 0), state.locale === "en" ? "normalized rows" : "统一价格口径"],
    [t("sourceCount"), `${manifest.source_health?.fresh || 0}/${manifest.source_health?.total || 0}`, state.locale === "en" ? "official + community" : "官方与社区来源"],
    [t("imageCount"), resources.filter((row) => row.free_image_generation).length, state.locale === "en" ? "officially verified" : "官方核验"],
  ];
  for (const [label, value, note] of metrics) {
    const card = element("article", "summary-card");
    card.append(element("span", "", label), element("strong", "", typeof value === "number" ? formatCount(value) : value), element("small", "", note));
    root.append(card);
  }
  $("last-updated").textContent = formatTime(manifest.radar_refreshed_at, state.locale);
  const revision = textValue(manifest.source_revision, "").slice(0, 7);
  $("snapshot-revision").textContent = `${manifest.package_version ? `v${manifest.package_version}` : ""}${revision ? ` · ${revision}` : ""}` || `schema ${manifest.schema_version || "—"}`;
  $("package-version").textContent = manifest.package_version ? `v${manifest.package_version}` : "v0.6.1";
}

function renderHealth() {
  const manifest = state.data.manifest || {};
  const health = manifest.source_health || {};
  const sources = items(state.data.sources);
  const fullyFresh = Number(health.fresh || 0) === Number(health.total || 0) && Number(health.total || 0) > 0;
  $("health-label").textContent = fullyFresh ? `${health.fresh}/${health.total} ${t("healthFresh")}` : t("healthPartial");
  $("source-health").classList.toggle("is-warning", !fullyFresh);
  $("health-updated").textContent = `${t("updated")} ${formatTime(manifest.radar_refreshed_at, state.locale)}`;
  $("health-total").textContent = `${health.fresh || 0}/${health.total || 0}`;
  const counts = $("health-counts");
  counts.replaceChildren();
  for (const [key, label] of [["fresh", t("fresh")], ["overdue", t("overdue")], ["verification_pending", t("pending")], ["failed", t("failed")], ["stale", t("stale")], ["never", t("never")]]) {
    const card = element("div", "health-count");
    card.append(element("span", "", label), element("strong", "", health[key] || 0));
    counts.append(card);
  }
  const root = $("health-sources");
  root.replaceChildren();
  const order = { failed: 0, verification_pending: 1, stale: 2, overdue: 3, never: 4, fresh: 5 };
  [...sources].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || textValue(a.name).localeCompare(textValue(b.name))).forEach((source) => {
    const row = element("div", "health-source");
    row.append(element("strong", "", source.name), element("span", "source-state", source.status), element("span", "", formatTime(source.last_success_at, state.locale)));
    root.append(row);
  });
}

function renderFeatured() {
  const show = state.group === "free" && state.view === "recommended";
  $("featured-section").hidden = !show;
  if (!show) return;
  const root = $("featured-resources");
  root.replaceChildren();
  recommendedRows(items(state.data.resources)).slice(0, 3).forEach((row, index) => root.append(createOfferCard(row, { locale: state.locale, primary: index === 0 })));
}

function renderChanges() {
  const section = $("important-changes");
  const rows = items(state.data.changes).filter((row) => ["high", "critical"].includes(row.importance) || IMPORTANT_CHANGES.has(row.change_type)).slice(0, 3);
  section.hidden = !(state.group === "free" && state.view === "recommended" && rows.length);
  const root = $("changes-list");
  root.replaceChildren();
  for (const row of rows) {
    const item = element("article", "change-item");
    item.append(element("span", "", changeLabel(row.change_type)), element("strong", "", `${textValue(row.provider)} · ${textValue(row.title)}`), element("p", "", formatTime(row.detected_at, state.locale)));
    root.append(item);
  }
}

function renderPriceCard(row) {
  const token = state.view === "token-prices";
  const card = element("article", "price-card");
  const header = element("div", "price-card-head");
  const copy = element("div");
  copy.append(element("h3", "price-card-title", row.model || row.title || row.gpu_model || "—"), element("p", "price-card-provider", textValue(row.provider)));
  header.append(copy, element("span", "price-badge", verificationLabel(row.verification_level, state.locale)));
  const metrics = element("div", "price-metrics");
  const values = token
    ? [[t("input"), formatUsd(row.input_per_mtok, state.locale)], [t("output"), formatUsd(row.output_per_mtok, state.locale)], [t("typical"), formatUsd(row.typical_cost, state.locale)]]
    : [[t("gpu"), textValue(row.gpu_model)], [t("hourly"), formatUsd(row.hourly_usd, state.locale)], [t("vram"), row.vram_gb == null ? "—" : `${row.vram_gb} GB`]];
  for (const [label, value] of values) {
    const metric = element("div", "price-metric");
    metric.append(element("span", "", label), element("strong", "", value));
    metrics.append(metric);
  }
  const footer = element("div", "price-card-footer");
  const link = safeLink(`${t("source")} ↗`, row.pricing_url, "");
  if (link) footer.append(link);
  footer.append(element("span", "", `${t("updated")} ${formatTime(row.verified_at, state.locale)}`));
  card.append(header, metrics, footer);
  return card;
}

function renderProviders() {
  const select = $("provider-filter");
  const selected = select.value;
  const providers = [...new Set(currentRows().map((row) => row.provider).filter(Boolean))].sort((a, b) => a.localeCompare(b, state.locale));
  select.replaceChildren(new Option(t("filters.allProviders"), ""));
  providers.forEach((provider) => select.append(new Option(provider, provider)));
  if (providers.includes(selected)) select.value = selected;
}

function renderNavigation() {
  document.querySelectorAll("[data-group]").forEach((button) => {
    const active = button.dataset.group === state.group;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  $("free-subnav").hidden = state.group !== "free";
  $("price-subnav").hidden = state.group !== "prices";
  $("summary").hidden = state.view !== "recommended";
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  document.querySelectorAll(".resource-filter").forEach((node) => { node.hidden = state.group === "prices"; });
  const recommendedSort = $("sort-filter").querySelector('option[value="recommended"]');
  const priceSort = $("sort-filter").querySelector('option[value="price"]');
  recommendedSort.hidden = state.group === "prices";
  recommendedSort.disabled = state.group === "prices";
  priceSort.hidden = state.group !== "prices";
  priceSort.disabled = state.group !== "prices";
  if ($("sort-filter").value === (state.group === "prices" ? "recommended" : "price")) {
    $("sort-filter").value = defaultSort();
  }
  if (state.group === "prices") {
    $("hero-title").textContent = t("priceHeroTitle");
    $("hero-description").textContent = t("priceHeroDescription");
    $("catalog-title").textContent = t("priceCatalogTitle");
    $("catalog-caption").textContent = t("priceCatalogCaption");
  } else {
    $("hero-title").textContent = t("hero.title");
    $("hero-description").textContent = t("hero.description");
    $("catalog-title").textContent = t("catalog.title");
    $("catalog-caption").textContent = t("catalog.caption");
  }
}

function renderResults() {
  const rows = filteredRows();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * PAGE_SIZE;
  const visible = rows.slice(start, start + PAGE_SIZE);
  const root = $("content");
  root.replaceChildren();
  if (!visible.length) root.append(element("article", "empty-card", t("noData")));
  else if (state.group === "prices") visible.forEach((row) => root.append(renderPriceCard(row)));
  else visible.forEach((row) => root.append(createOfferCard(row, { locale: state.locale })));
  $("load-status").textContent = `${t("loaded")} ${visible.length} / ${rows.length}`;
  const pager = $("pager");
  pager.hidden = rows.length <= PAGE_SIZE;
  $("previous-page").disabled = state.page <= 1;
  $("next-page").disabled = state.page >= pages;
  $("page-label").textContent = t("page").replace("{page}", state.page).replace("{pages}", pages);
  root.setAttribute("aria-busy", "false");
}

function render() {
  renderNavigation();
  renderSummary();
  renderHealth();
  renderFeatured();
  renderChanges();
  renderProviders();
  renderResults();
  writeRoute();
}

function setLocale(locale) {
  state.locale = locale === "en" ? "en" : "zh-CN";
  localStorage.setItem("ai-radar-locale", state.locale);
  document.documentElement.lang = state.locale;
  document.title = state.locale === "en" ? "AI Resource Radar — verified free AI and prices" : "AI Resource Radar — AI 免费资源与价格雷达";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const value = COPY[state.locale][node.dataset.i18n];
    if (value) node.textContent = value;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    const value = COPY[state.locale][node.dataset.i18nPlaceholder];
    if (value) node.placeholder = value;
  });
  if (state.data.manifest) render();
}

function resetPageAndRender() { state.page = 1; render(); }
function currentDownloadKey() { return state.view === "token-prices" ? "tokenPrices" : state.view === "gpu-prices" ? "gpuPrices" : "resources"; }

async function load() {
  try {
    const entries = await Promise.all(Object.entries(DATA).map(async ([key, url]) => {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`public_snapshot_${response.status}`);
      return [key, await response.json()];
    }));
    entries.forEach(([key, value]) => { state.data[key] = value; });
    readRoute();
    render();
  } catch {
    $("source-health").classList.add("is-error");
    $("health-label").textContent = state.locale === "en" ? "Snapshot unavailable" : "公开快照不可用";
    $("load-status").classList.add("is-error");
    $("load-status").textContent = state.locale === "en" ? "The last public snapshot could not be loaded." : "暂时无法读取公开快照。";
    $("content").setAttribute("aria-busy", "false");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  state.locale = localStorage.getItem("ai-radar-locale") || (/^en/i.test(navigator.language) ? "en" : "zh-CN");
  $("language-toggle").addEventListener("click", () => setLocale(state.locale === "en" ? "zh-CN" : "en"));
  document.querySelectorAll("[data-group]").forEach((button) => button.addEventListener("click", () => {
    state.group = button.dataset.group;
    state.view = defaultView(state.group);
    state.page = 1;
    $("provider-filter").value = "";
    $("sort-filter").value = defaultSort();
    render();
  }));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
    state.view = button.dataset.view;
    state.group = groupFor(state.view);
    state.page = 1;
    $("provider-filter").value = "";
    $("sort-filter").value = defaultSort();
    render();
  }));
  ["search-input", "provider-filter", "verification-filter", "card-filter", "mainland-filter", "sort-filter"].forEach((id) => $(id).addEventListener("input", resetPageAndRender));
  $("clear-filters").addEventListener("click", () => {
    $("search-input").value = "";
    $("provider-filter").value = "";
    $("verification-filter").value = "all";
    $("card-filter").value = "all";
    $("mainland-filter").value = "all";
    $("sort-filter").value = defaultSort();
    resetPageAndRender();
  });
  $("previous-page").addEventListener("click", () => { if (state.page > 1) { state.page -= 1; render(); $("catalog-title").scrollIntoView({ block: "start" }); } });
  $("next-page").addEventListener("click", () => { state.page += 1; render(); $("catalog-title").scrollIntoView({ block: "start" }); });
  $("download-json").addEventListener("click", () => { location.href = DATA[currentDownloadKey()]; });
  $("download-csv").addEventListener("click", () => { const key = currentDownloadKey() === "tokenPrices" ? "token-prices" : currentDownloadKey() === "gpuPrices" ? "gpu-prices" : "resources"; location.href = `data/${key}.csv`; });
  window.addEventListener("popstate", () => { readRoute(); render(); });
  setLocale(state.locale);
  load();
});
