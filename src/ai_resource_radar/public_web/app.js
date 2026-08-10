/* AI Resource Radar public site: static, read-only, and deliberately dependency-free. */
import { readStaticRoute, writeStaticRoute } from "./ui-modules.js";

(function () {
  "use strict";

  const DATA = {
    manifest: "data/manifest.json",
    summary: "data/summary.json",
    sources: "data/source-health.json",
    resources: "data/resources.json",
    tokenPrices: "data/token-prices.json",
    gpuPrices: "data/gpu-prices.json",
    changes: "data/changes.json"
  };
  const COPY = {
    "zh-CN": {
      loading: "正在读取本地数据…", loaded: "已加载", failed: "公开快照暂时不可用",
      health: "来源新鲜", partial: "部分来源需复核", all: "全部", no: "无需信用卡",
      official: "官方核验", community: "社区基线", unknown: "待确认", supported: "大陆可用",
      unsupported: "大陆不可用", recommended: "推荐", token: "免费 Token", gpu: "免费 GPU",
      grant: "资助", tokenPrices: "Token 价格", gpuPrices: "GPU 价格", changes: "变化",
      about: "来源健康", search: "搜索", card: "信用卡", mainland: "大陆状态",
      provider: "供应商", sort: "排序", clear: "清除筛选", allProviders: "全部供应商",
      best: "推荐", updated: "最近更新", price: "价格从低", alpha: "供应商 A-Z",
      free: "免费资源", priceRows: "价格条目", sources: "来源", changeRows: "近30天变化",
      get: "送什么", how: "怎么领", limits: "限制与资格", evidence: "官方证据",
      visit: "打开来源", noData: "没有符合当前筛选的条目。", source: "来源",
      sourceStatus: "来源状态", refreshed: "最近刷新", age: "数据年龄", readOnly: "只读快照",
      downloadJson: "下载 JSON", downloadCsv: "下载 CSV", changesTitle: "最近变化",
      aboutTitle: "来源健康与使用说明", evidenceNote: "页面只聚合公开资料；使用前请打开官方页面复核。",
      fallback: "暂无双语专用说明，以下为规范化公开字段。", loadMore: "加载更多",
      skip: "跳到内容", "health.loading": "读取来源", "tabs.recommended": "推荐",
      "tabs.token": "免费 Token", "tabs.gpu": "免费 GPU", "tabs.grant": "资助",
      "tabs.tokenPrices": "Token 价格", "tabs.gpuPrices": "GPU 价格", "tabs.changes": "变化",
      "tabs.about": "来源健康", "hero.eyebrow": "只读目录 · 官方证据",
      "hero.title": "先看清楚，再开始用。",
      "hero.description": "把“送什么、怎么领、有什么限制、证据在哪里”放在同一张卡片里。数据由本地 JSON 提供，页面不会提交表单或代你操作账号。",
      "hero.updated": "数据更新时间", "catalog.kicker": "资源目录", "catalog.title": "浏览资源",
      "catalog.caption": "搜索供应商，按核验、信用卡和地区状态筛选。",
      "download.json": "下载 JSON", "download.csv": "下载 CSV", "filters.search": "搜索",
      "filters.searchPlaceholder": "供应商、模型或关键词", "filters.provider": "供应商",
      "filters.allProviders": "全部供应商", "filters.verification": "核验", "filters.all": "全部",
      "filters.official": "仅官方", "filters.community": "社区或待核验", "filters.card": "信用卡",
      "filters.noCard": "无需信用卡", "filters.cardRequired": "需要或待确认",
      "filters.mainland": "大陆状态", "filters.supported": "可用", "filters.unknown": "待确认",
      "filters.unsupported": "不支持", "filters.sort": "排序", "filters.clear": "清除筛选",
      "sort.recommended": "推荐度", "sort.updated": "更新时间", "sort.price": "价格从低",
      "sort.provider": "供应商", "status.loading": "正在读取本地数据…",
      "footer.readOnly": "只读目录，不会代你注册、提交或生成海报。", "footer.github": "GitHub 源码"
    },
    en: {
      loading: "Loading local data…", loaded: "Loaded", failed: "Public snapshot unavailable",
      health: "Sources fresh", partial: "Some sources need review", all: "All", no: "No card",
      official: "Official", community: "Community baseline", unknown: "Unknown", supported: "Mainland supported",
      unsupported: "Mainland unavailable", recommended: "Recommended", token: "Free tokens", gpu: "Free GPU",
      grant: "Grants", tokenPrices: "Token prices", gpuPrices: "GPU prices", changes: "Changes",
      about: "Source health", search: "Search", card: "Card", mainland: "Mainland status",
      provider: "Provider", sort: "Sort", clear: "Clear filters", allProviders: "All providers",
      best: "Recommended", updated: "Recently updated", price: "Lowest price", alpha: "Provider A-Z",
      free: "Free resources", priceRows: "Price rows", sources: "Sources", changeRows: "Changes (30d)",
      get: "What you get", how: "How to claim", limits: "Limits & eligibility", evidence: "Evidence",
      visit: "Open source", noData: "No rows match the current filters.", source: "Source",
      sourceStatus: "Source status", refreshed: "Last refresh", age: "Data age", readOnly: "Read-only snapshot",
      downloadJson: "Download JSON", downloadCsv: "Download CSV", changesTitle: "Recent changes",
      aboutTitle: "Source health and usage notes", evidenceNote: "This is a public aggregation; verify the official page before using an offer.",
      fallback: "No dedicated translation; showing normalized public fields.", loadMore: "Load more",
      skip: "Skip to content", "health.loading": "Loading sources", "tabs.recommended": "Recommended",
      "tabs.token": "Free tokens", "tabs.gpu": "Free GPU", "tabs.grant": "Grants",
      "tabs.tokenPrices": "Token prices", "tabs.gpuPrices": "GPU prices", "tabs.changes": "Changes",
      "tabs.about": "Source health", "hero.eyebrow": "READ-ONLY · OFFICIAL EVIDENCE",
      "hero.title": "Know the offer before you claim it.",
      "hero.description": "See what you get, how to claim it, the limits, and the evidence on one card. Local JSON powers this read-only page; it never submits forms or touches your accounts.",
      "hero.updated": "Data updated", "catalog.kicker": "CATALOGUE", "catalog.title": "Browse resources",
      "catalog.caption": "Search providers and filter by verification, card requirement, and mainland availability.",
      "download.json": "Download JSON", "download.csv": "Download CSV", "filters.search": "Search",
      "filters.searchPlaceholder": "Provider, model, or keyword", "filters.provider": "Provider",
      "filters.allProviders": "All providers", "filters.verification": "Verification", "filters.all": "All",
      "filters.official": "Official only", "filters.community": "Community or pending", "filters.card": "Card",
      "filters.noCard": "No card", "filters.cardRequired": "Required or unknown",
      "filters.mainland": "Mainland", "filters.supported": "Supported", "filters.unknown": "Unknown",
      "filters.unsupported": "Unsupported", "filters.sort": "Sort", "filters.clear": "Clear filters",
      "sort.recommended": "Recommended", "sort.updated": "Updated", "sort.price": "Lowest price",
      "sort.provider": "Provider", "status.loading": "Loading local data…",
      "footer.readOnly": "Read-only catalogue. It never registers, submits, or generates posters for you.", "footer.github": "GitHub source"
    }
  };
  const state = { locale: "zh-CN", tab: "recommended", data: {}, rows: [], filtered: [], limit: 100 };
  const validTabs = new Set(["recommended", "token", "gpu", "grant", "token-prices", "gpu-prices", "changes", "about"]);
  const $ = (id) => document.getElementById(id);
  const text = (value) => value == null || value === "" ? "—" : String(value);
  const t = (key) => (COPY[state.locale] && COPY[state.locale][key]) || key;
  const unwrap = (payload, keys) => {
    if (Array.isArray(payload)) return payload;
    for (const key of keys) if (Array.isArray(payload && payload[key])) return payload[key];
    return [];
  };
  const safeUrl = (value) => {
    try {
      const url = new URL(String(value || ""), window.location.href);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) { return ""; }
  };
  const presentation = (row) => {
    const p = row && row.presentation;
    return (p && (p[state.locale] || p.en || p["zh-CN"])) || {};
  };
  const labelVerification = (level) => {
    if (["official_api", "official_page"].includes(level)) return t("official");
    return t("community");
  };
  const labelMainland = (status) => ({ supported: t("supported"), unsupported: t("unsupported"), unknown: t("unknown") }[status] || t("unknown"));
  const add = (parent, tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = value;
    parent.appendChild(node);
    return node;
  };
  const addLink = (parent, url, label) => {
    const safe = safeUrl(url);
    if (!safe) return null;
    const link = add(parent, "a", "source-link", label);
    link.href = safe;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    return link;
  };
  const metric = (parent, label, value) => {
    const item = add(parent, "div", "metric");
    add(item, "dt", null, label);
    add(item, "dd", null, text(value));
  };
  const formatNumber = (value) => typeof value === "number" ? new Intl.NumberFormat(state.locale).format(value) : text(value);
  const formatDate = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return Number.isNaN(d.valueOf()) ? String(value) : d.toLocaleString(state.locale, { dateStyle: "medium", timeStyle: "short" });
  };
  const priority = (row) => ({ A: 0, B: 1, C: 2, D: 3 }[row.priority_tier] ?? 4);
  const sortRows = (rows) => {
    const sort = $("sort-filter") && $("sort-filter").value;
    return [...rows].sort((a, b) => {
      if (sort === "price") return Number(a.typical_cost ?? a.hourly_usd ?? Infinity) - Number(b.typical_cost ?? b.hourly_usd ?? Infinity);
      if (sort === "provider") return text(a.provider).localeCompare(text(b.provider));
      if (sort === "updated") return text(b.last_changed_at || b.verified_at).localeCompare(text(a.last_changed_at || a.verified_at));
      return priority(a) - priority(b) || (a.mainland_status === "supported" ? -1 : 0) - (b.mainland_status === "supported" ? -1 : 0) || text(a.provider).localeCompare(text(b.provider));
    });
  };
  function saveUrl() {
    writeStaticRoute({ tab: state.tab, query: $("search-input").value });
    const url = new URL(window.location.href);
    ["provider-filter", "verification-filter", "card-filter", "mainland-filter", "sort-filter"].forEach((id) => {
      const value = $(id).value;
      const key = id.replace("-filter", "");
      if (value && value !== "all" && value !== "recommended") url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    });
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }
  function readUrl() {
    const p = new URLSearchParams(location.search);
    const route = readStaticRoute(validTabs);
    state.tab = route.tab;
    $("search-input").value = route.query;
    ["provider-filter", "verification-filter", "card-filter", "mainland-filter", "sort-filter"].forEach((id) => { const v = p.get(id.replace("-filter", "")); if (v && $(id).querySelector(`option[value="${CSS.escape(v)}"]`)) $(id).value = v; });
  }
  function setLanguage(locale) {
    state.locale = locale === "en" ? "en" : "zh-CN";
    localStorage.setItem("ai-radar-locale", state.locale);
    document.documentElement.lang = state.locale;
    document.title = state.locale === "en"
      ? "AI Resource Radar — Verified free AI and prices"
      : "AI Resource Radar — AI 免费资源与价格雷达";
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.dataset.i18n;
      if (COPY[state.locale][key]) node.textContent = COPY[state.locale][key];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => { node.placeholder = COPY[state.locale][node.dataset.i18nPlaceholder] || node.placeholder; });
    if (state.data.manifest) {
      $("health-label").textContent = state.data.manifest.status === "partial" ? t("partial") : t("health");
      updateProviders();
    }
    render();
  }
  function currentRows() {
    if (state.tab === "token-prices") return unwrap(state.data.tokenPrices, ["prices", "items"]);
    if (state.tab === "gpu-prices") return unwrap(state.data.gpuPrices, ["prices", "items"]);
    if (state.tab === "changes") return unwrap(state.data.changes, ["changes", "items"]);
    const resources = unwrap(state.data.resources, ["resources", "offers", "items"]);
    if (state.tab === "recommended") {
      const seen = new Set();
      return sortRows(resources.filter((row) =>
        ["official_api", "official_page"].includes(row.verification_level) &&
        ["A", "B"].includes(row.priority_tier) && row.requires_card === "no" &&
        ["supported", "unknown"].includes(row.mainland_status)
      )).filter((row) => {
        const provider = String(row.provider || "").toLowerCase();
        if (seen.has(provider)) return false;
        seen.add(provider); return true;
      }).slice(0, 12);
    }
    return resources.filter((row) => row.kind === state.tab);
  }
  function renderSummary() {
    const root = $("summary"); root.replaceChildren();
    const counts = (state.data.manifest || {}).counts || {};
    [[t("free"), counts.resources], [t("priceRows"), Number(counts.token_prices || 0) + Number(counts.gpu_prices || 0)], [t("sources"), ((state.data.sources || {}).items || []).length], [t("changeRows"), counts.changes]].forEach(([label, value]) => { const card = add(root, "div", "summary-card"); add(card, "span", "summary-label", label); add(card, "strong", "summary-value", formatNumber(value || 0)); });
    $("last-updated").textContent = formatDate((state.data.manifest || {}).generated_at);
    $("manifest-version").textContent = `schema ${text((state.data.manifest || {}).schema_version)} · ${text((state.data.manifest || {}).status)}`;
  }
  function renderCard(row) {
    const isPrice = state.tab.endsWith("prices");
    const card = add($("content"), "article", "resource-card");
    const head = add(card, "div", "card-head");
    const title = row.model || row.title || row.provider || "—";
    add(head, "div", "card-title", title);
    const badges = add(head, "div", "badges");
    add(badges, "span", "badge", labelVerification(row.verification_level));
    if (!isPrice && row.priority_tier) add(badges, "span", `badge tier-${row.priority_tier.toLowerCase()}`, `Tier ${row.priority_tier}`);
    if (!isPrice && row.mainland_status) add(badges, "span", "badge badge-muted", labelMainland(row.mainland_status));
    add(card, "p", "provider-line", text(row.provider));
    const metrics = add(card, "dl", "metrics");
    if (isPrice) {
      if (state.tab === "token-prices") { metric(metrics, "Input / 1M", row.input_per_mtok == null ? "—" : `$${row.input_per_mtok}`); metric(metrics, "Output / 1M", row.output_per_mtok == null ? "—" : `$${row.output_per_mtok}`); metric(metrics, "Typical", row.typical_cost == null ? "—" : `$${row.typical_cost}`); }
      else { metric(metrics, "GPU", row.gpu_model); metric(metrics, "Hourly", row.hourly_usd == null ? "—" : `$${row.hourly_usd}`); metric(metrics, "VRAM", row.vram_gb == null ? "—" : `${row.vram_gb} GB`); }
    } else {
      metric(metrics, t("get"), row.quota_value == null ? row.offer_type : `${formatNumber(row.quota_value)} ${text(row.quota_unit)}`);
      metric(metrics, "Reset", row.reset_period || "—");
      metric(metrics, t("card"), row.requires_card || "—");
    }
    const p = presentation(row);
    if (!isPrice && p.benefit_summary) { add(card, "h4", "detail-heading", t("get")); add(card, "p", "detail-copy", p.benefit_summary); }
    if (!isPrice && p.usage_steps && p.usage_steps.length) { add(card, "h4", "detail-heading", t("how")); const list = add(card, "ol", "steps"); p.usage_steps.slice(0, 5).forEach((step) => add(list, "li", null, step)); }
    if (!isPrice && p.caveats && p.caveats.length) { add(card, "h4", "detail-heading", t("limits")); const list = add(card, "ul", "caveats"); p.caveats.slice(0, 5).forEach((item) => add(list, "li", null, item)); }
    const footer = add(card, "div", "card-footer");
    const evidence = row.evidence || {};
    addLink(footer, evidence.source_url || row.pricing_url || row.homepage_url, t("visit"));
    add(footer, "span", "verified-at", `${t("updated")}: ${formatDate(row.last_seen_at || row.verified_at || row.detected_at)}`);
    return card;
  }
  function renderChanges(rows) {
    const root = $("content");
    rows.slice(0, 100).forEach((row) => { const card = add(root, "article", "resource-card"); add(card, "div", "card-title", `${text(row.provider)} · ${text(row.title)}`); add(card, "p", "provider-line", `${text(row.change_type)} · ${formatDate(row.detected_at)}`); add(card, "pre", "change-json", JSON.stringify(row.changed_fields || {}, null, 2)); });
  }
  function renderAbout() {
    const root = $("content"); add(root, "p", "about-note", t("evidenceNote"));
    (state.data.sources && state.data.sources.items || []).forEach((row) => { const card = add(root, "article", "source-row"); add(card, "strong", null, text(row.name)); add(card, "span", "badge", text(row.status)); add(card, "span", "verified-at", `${t("refreshed")}: ${formatDate(row.last_success_at)}`); });
  }
  function filterRows() {
    let rows = currentRows(); const q = $("search-input").value.trim().toLowerCase();
    const provider = $("provider-filter").value; const verification = $("verification-filter").value; const card = $("card-filter").value; const mainland = $("mainland-filter").value;
    rows = rows.filter((row) => (!q || `${row.provider || ""} ${row.title || ""} ${row.model || ""}`.toLowerCase().includes(q)) && (!provider || row.provider === provider) && (verification === "all" || (verification === "official" ? ["official_api", "official_page"].includes(row.verification_level) : !["official_api", "official_page"].includes(row.verification_level))) && (card === "all" || (card === "no" ? row.requires_card === "no" : row.requires_card !== "no")) && (mainland === "all" || row.mainland_status === mainland));
    state.filtered = sortRows(rows); return state.filtered;
  }
  function render() {
    document.querySelectorAll(".tab").forEach((tab) => {
      const active = tab.dataset.tab === state.tab;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active) $("content").setAttribute("aria-labelledby", tab.id);
    });
    const about = state.tab === "about"; const changes = state.tab === "changes";
    document.querySelector(".filters").hidden = about;
    $("download-json").hidden = about; $("download-csv").hidden = about;
    renderSummary(); const root = $("content"); root.setAttribute("aria-busy", "true"); root.replaceChildren();
    if (about) {
      renderAbout();
      $("load-status").textContent = `${t("loaded")}: ${(state.data.sources && state.data.sources.items || []).length}`;
      root.setAttribute("aria-busy", "false");
      saveUrl();
      return;
    }
    const rows = filterRows();
    const visible = state.tab === "recommended" ? 12 : state.limit;
    if (changes) renderChanges(rows); else rows.slice(0, visible).forEach(renderCard);
    $("load-status").textContent = `${t("loaded")}: ${Math.min(rows.length, visible)} / ${rows.length}`;
    $("load-more").textContent = t("loadMore");
    $("load-more").hidden = about || changes || rows.length <= visible;
    root.setAttribute("aria-busy", "false");
    saveUrl();
  }
  function updateProviders() {
    const select = $("provider-filter"); const values = [...new Set(currentRows().map((row) => row.provider).filter(Boolean))].sort();
    const previous = select.value; select.replaceChildren(); add(select, "option", null, t("allProviders")).value = "";
    values.forEach((value) => { const option = add(select, "option", null, value); option.value = value; });
    if (values.includes(previous)) select.value = previous;
  }
  async function load() {
    $("load-status").setAttribute("aria-busy", "true");
    try {
      const entries = await Promise.all(Object.entries(DATA).map(async ([key, url]) => [key, await fetch(url, { cache: "no-store" }).then((response) => { if (!response.ok) throw new Error(response.status); return response.json(); })]));
      entries.forEach(([key, value]) => { state.data[key] = value; });
      $("health-label").textContent = (state.data.manifest || {}).status === "partial" ? t("partial") : t("health");
      readUrl(); updateProviders(); readUrl(); render();
    } catch (_) { $("health-label").textContent = t("failed"); $("load-status").textContent = t("failed"); }
    finally { $("load-status").setAttribute("aria-busy", "false"); }
  }
  document.addEventListener("DOMContentLoaded", () => {
    state.locale = localStorage.getItem("ai-radar-locale") || (/^en/i.test(navigator.language) ? "en" : "zh-CN");
    $("language-toggle").addEventListener("click", () => setLanguage(state.locale === "en" ? "zh-CN" : "en"));
    const tabs = [...document.querySelectorAll(".tab")];
    tabs.forEach((tab) => tab.addEventListener("click", () => { state.tab = tab.dataset.tab; state.limit = 100; updateProviders(); render(); }));
    $("main-nav").addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const current = Math.max(0, tabs.indexOf(document.activeElement));
      const target = event.key === "Home" ? 0
        : event.key === "End" ? tabs.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      tabs[target].focus();
      tabs[target].click();
    });
    ["search-input", "provider-filter", "verification-filter", "card-filter", "mainland-filter", "sort-filter"].forEach((id) => $(id).addEventListener("input", () => { state.limit = 100; render(); }));
    $("load-more").addEventListener("click", () => { state.limit += 100; render(); });
    $("clear-filters").addEventListener("click", () => { $("search-input").value = ""; ["provider-filter", "verification-filter", "card-filter", "mainland-filter", "sort-filter"].forEach((id) => { if (id === "provider-filter") $(id).value = ""; else if (id === "sort-filter") $(id).value = "recommended"; else $(id).value = "all"; }); render(); });
    $("download-json").addEventListener("click", () => { const key = state.tab === "token-prices" ? "tokenPrices" : state.tab === "gpu-prices" ? "gpuPrices" : state.tab === "changes" ? "changes" : "resources"; window.location.href = DATA[key]; });
    $("download-csv").addEventListener("click", () => { const key = state.tab === "token-prices" ? "token-prices" : state.tab === "gpu-prices" ? "gpu-prices" : state.tab === "changes" ? "changes" : "resources"; window.location.href = `data/${key}.csv`; });
    setLanguage(state.locale); load();
  });
})();
