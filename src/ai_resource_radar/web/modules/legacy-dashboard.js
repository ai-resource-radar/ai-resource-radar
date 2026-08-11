/*
 * Compatibility controller for the local dashboard.
 *
 * Rendering and formatting live in modules/components.js and modules/views/*.
 * This file intentionally keeps only DOM wiring, routing, and lifecycle work
 * so the historic /ai-resources.js entry remains a tiny compatibility shim.
 */
import { beginViewRequest, fetchJson, fetchViewJson, isAbortError } from "/ai-radar-assets/modules/api.js";
import { KNOWN_VIEWS, readRoute, writeRoute } from "/ai-radar-assets/modules/state-router.js";
import {
  actionQuota,
  benefitSummary,
  caveats,
  changeLabel,
  compactNumber,
  formatContext,
  formatTime,
  formatUsd,
  guide,
  kindLabel,
  resetLabel,
  usageSteps,
} from "/ai-radar-assets/modules/formatters.js";
import {
  createDialogActions,
  element,
  installDialog,
  metric,
  providerInitials,
  renderPricingMethod,
  renderRankingExplainer,
  replaceSelectOptions,
  safeLink,
  updateHero,
} from "/ai-radar-assets/modules/components.js";
import { configurePricingControls, loadGpuPrices, loadTokenPrices, renderComparison, updateCompareBar } from "/ai-radar-assets/modules/views/pricing.js";

"use strict";

export function mountDashboard({ viewModules = {} } = {}) {
  const dom = {
    summaryRoot: document.querySelector("#radar-summary"),
    featuredRoot: document.querySelector("#featured-resources"),
    featuredSection: document.querySelector("#featured-section"),
    resultsRoot: document.querySelector("#radar-results"),
    refreshButton: document.querySelector("#refresh-radar"),
    refreshState: document.querySelector("#refresh-state"),
    queryInput: document.querySelector("#radar-query"),
    verifiedOnly: document.querySelector("#verified-only"),
    noCard: document.querySelector("#no-card"),
    freeImageGeneration: document.querySelector("#free-image-generation"),
    mainlandSupported: document.querySelector("#mainland-supported"),
    mainlandUnknown: document.querySelector("#mainland-unknown"),
    mainlandUnsupported: document.querySelector("#mainland-unsupported"),
    filters: document.querySelector(".radar-filters"),
    filterToggle: document.querySelector("#toggle-filters"),
    tabs: [...document.querySelectorAll("[data-view]")],
    viewSubnav: document.querySelector("#view-subnav"),
    resourceSubnav: document.querySelector("#resource-subnav"),
    priceSubnav: document.querySelector("#price-subnav"),
    freeQuickFilters: document.querySelector("#free-quick-filters"),
    dialog: document.querySelector("#offer-dialog"),
    detailRoot: document.querySelector("#offer-detail"),
    closeDialogButton: document.querySelector("#close-offer-dialog"),
    heroPickTitle: document.querySelector("#hero-pick-title"),
    heroPickNote: document.querySelector("#hero-pick-note"),
    lastVerified: document.querySelector("#last-verified"),
    sourceHealth: document.querySelector("#source-health"),
    sourceHealthBar: document.querySelector("#source-health-bar"),
    healthySourceCount: document.querySelector("#healthy-source-count"),
    failedSourceCount: document.querySelector("#failed-source-count"),
    changePreview: document.querySelector("#change-preview"),
    catalogTitle: document.querySelector("#catalog-title"),
    catalogCaption: document.querySelector("#catalog-caption"),
    heroEyebrow: document.querySelector("#hero-eyebrow"),
    heroTitle: document.querySelector("#hero-title"),
    heroCopy: document.querySelector("#hero-copy"),
    heroTrust: document.querySelector(".hero-trust"),
    heroPickLabel: document.querySelector("#hero-pick-label"),
    pricingControls: document.querySelector("#pricing-controls"),
    pricingSort: document.querySelector("#pricing-sort"),
    pricingDirection: document.querySelector("#pricing-direction"),
    pricingProvider: document.querySelector("#pricing-provider"),
    tokenPriceControls: [...document.querySelectorAll(".token-price-control")],
    tokenVerification: document.querySelector("#token-verification"),
    tokenMinContext: document.querySelector("#token-min-context"),
    tokenMaxTypical: document.querySelector("#token-max-typical"),
    tokenMaxInput: document.querySelector("#token-max-input"),
    tokenMaxOutput: document.querySelector("#token-max-output"),
    tokenCache: document.querySelector("#token-cache"),
    gpuPriceControls: [...document.querySelectorAll(".gpu-price-control")],
    gpuModel: document.querySelector("#gpu-model"),
    gpuMinVram: document.querySelector("#gpu-min-vram"),
    gpuMaxHourly: document.querySelector("#gpu-max-hourly"),
    gpuBilling: document.querySelector("#gpu-billing"),
    gpuTier: document.querySelector("#gpu-tier"),
    gpuPriceMode: document.querySelector("#gpu-price-mode"),
    gpuHours: document.querySelector("#gpu-hours"),
    pricingFilterSummary: document.querySelector("#pricing-filter-summary"),
    pricingAdvanced: document.querySelector("#pricing-advanced"),
    togglePriceFilters: document.querySelector("#toggle-price-filters"),
    priceCompareBar: document.querySelector("#price-compare-bar"),
    priceCompareCount: document.querySelector("#price-compare-count"),
    openPriceCompare: document.querySelector("#open-price-compare"),
    browserGrid: document.querySelector(".browser-grid"),
    radarSidebar: document.querySelector(".radar-sidebar"),
    sourceHealthDisclosure: document.querySelector("#source-health-disclosure"),
  };

  const route = readRoute();
  const state = {
    currentView: route.view,
    comparedPrices: new Map(),
    providerProfiles: new Map(),
    tipFilters: {
      status: route.filters.tip_status || "",
      category: route.filters.tip_category || "",
      risk: route.filters.tip_risk || "",
      source: route.filters.tip_source || "",
      scope: route.filters.tip_scope || "",
    },
    pendingRouteFilters: route.filters,
    searchTimer: null,
    refreshTimer: null,
  };
  dom.queryInput.value = route.query;

  function routeBoolean(filters, key, fallback) {
    if (!(key in filters)) return fallback;
    return filters[key] === "1" || filters[key] === "true";
  }

  function setSelectValue(select, value) {
    if (!value) return;
    if (![...select.options].some((option) => option.value === value)) select.append(new Option(value, value));
    select.value = value;
  }

  function applyBaseRouteFilters(filters) {
    dom.verifiedOnly.checked = routeBoolean(filters, "verified", true);
    dom.noCard.checked = routeBoolean(filters, "no_card", true);
    dom.freeImageGeneration.checked = routeBoolean(filters, "image", false);
    const mainland = new Set((filters.mainland || "supported,unknown").split(",").filter(Boolean));
    dom.mainlandSupported.checked = mainland.has("supported");
    dom.mainlandUnknown.checked = mainland.has("unknown");
    dom.mainlandUnsupported.checked = mainland.has("unsupported");
  }

  function applyPricingRouteFilters(filters) {
    setSelectValue(dom.pricingSort, filters.sort);
    setSelectValue(dom.pricingDirection, filters.direction);
    setSelectValue(dom.pricingProvider, filters.provider);
    setSelectValue(dom.tokenVerification, filters.verification);
    setSelectValue(dom.tokenMinContext, filters.min_context);
    dom.tokenMaxTypical.value = filters.max_typical || "";
    dom.tokenMaxInput.value = filters.max_input || "";
    dom.tokenMaxOutput.value = filters.max_output || "";
    setSelectValue(dom.tokenCache, filters.cache);
    setSelectValue(dom.gpuModel, filters.gpu);
    setSelectValue(dom.gpuMinVram, filters.min_vram);
    dom.gpuMaxHourly.value = filters.max_hourly || "";
    setSelectValue(dom.gpuBilling, filters.billing);
    setSelectValue(dom.gpuTier, filters.tier);
    setSelectValue(dom.gpuPriceMode, filters.price_mode);
    setSelectValue(dom.gpuHours, filters.hours);
    const advanced = filters.advanced === "1";
    dom.pricingAdvanced.hidden = !advanced;
    dom.togglePriceFilters.setAttribute("aria-expanded", String(advanced));
    dom.togglePriceFilters.textContent = advanced ? "收起高级筛选" : "展开高级筛选";
  }

  function collectRouteFilters() {
    const filters = {};
    if (!dom.verifiedOnly.checked) filters.verified = "0";
    if (!dom.noCard.checked) filters.no_card = "0";
    if (dom.freeImageGeneration.checked) filters.image = "1";
    const mainland = [
      dom.mainlandSupported.checked && "supported",
      dom.mainlandUnknown.checked && "unknown",
      dom.mainlandUnsupported.checked && "unsupported",
    ].filter(Boolean).join(",");
    if (mainland !== "supported,unknown") filters.mainland = mainland;
    if (["token-prices", "gpu-prices"].includes(state.currentView)) {
      const defaults = state.currentView === "token-prices" ? { sort: "typical" } : { sort: "hourly" };
      if (dom.pricingSort.value && dom.pricingSort.value !== defaults.sort) filters.sort = dom.pricingSort.value;
      if (dom.pricingDirection.value && dom.pricingDirection.value !== "asc") filters.direction = dom.pricingDirection.value;
      if (dom.pricingProvider.value) filters.provider = dom.pricingProvider.value;
      if (!dom.pricingAdvanced.hidden) filters.advanced = "1";
      if (state.currentView === "token-prices") {
        if (dom.tokenVerification.value !== "all") filters.verification = dom.tokenVerification.value;
        if (dom.tokenMinContext.value) filters.min_context = dom.tokenMinContext.value;
        if (dom.tokenMaxTypical.value) filters.max_typical = dom.tokenMaxTypical.value;
        if (dom.tokenMaxInput.value) filters.max_input = dom.tokenMaxInput.value;
        if (dom.tokenMaxOutput.value) filters.max_output = dom.tokenMaxOutput.value;
        if (dom.tokenCache.value !== "any") filters.cache = dom.tokenCache.value;
      } else {
        if (dom.gpuModel.value) filters.gpu = dom.gpuModel.value;
        if (dom.gpuMinVram.value) filters.min_vram = dom.gpuMinVram.value;
        if (dom.gpuMaxHourly.value) filters.max_hourly = dom.gpuMaxHourly.value;
        if (dom.gpuBilling.value) filters.billing = dom.gpuBilling.value;
        if (dom.gpuTier.value) filters.tier = dom.gpuTier.value;
        if (dom.gpuPriceMode.value !== "all") filters.price_mode = dom.gpuPriceMode.value;
        if (dom.gpuHours.value !== "10") filters.hours = dom.gpuHours.value;
      }
    }
    if (state.currentView === "tips") {
      Object.entries(state.tipFilters).forEach(([key, value]) => {
        if (value) filters[`tip_${key}`] = value;
      });
    }
    return filters;
  }

  function syncRoute() {
    writeRoute(state.currentView, dom.queryInput.value, collectRouteFilters());
  }

  applyBaseRouteFilters(route.filters);

  const ctx = {
    dom,
    state,
    element,
    safeLink,
    metric,
    providerInitials,
    replaceSelectOptions,
    fetchJson,
    fetchViewJson,
    beginViewRequest,
    isAbortError,
    actionQuota,
    benefitSummary,
    caveats,
    compactNumber,
    formatContext,
    formatTime,
    formatUsd,
    guide,
    kindLabel,
    resetLabel,
    usageSteps,
    changeLabel,
    syncRoute,
    loadCurrentView: () => loadCurrentView(),
  };
  const dialogController = installDialog(dom.dialog, dom.closeDialogButton, dom.detailRoot);
  const dialogActions = createDialogActions({ dialog: dom.dialog, detailRoot: dom.detailRoot, dialogController, ctx });
  Object.assign(ctx, dialogActions, { dialog: dom.dialog, dialogController });

  async function loadProviderProfiles() {
    try {
      const payload = await fetchJson("/api/ai-resources/providers");
      const integrations = new Map((payload.integrations || []).map((row) => [row.slug, row]));
      (payload.providers || []).forEach((profile) => {
        const combined = { ...profile, integration: integrations.get(profile.slug) || null };
        [profile.name, profile.provider, profile.slug, ...(profile.aliases || [])]
          .filter(Boolean)
          .forEach((name) => state.providerProfiles.set(String(name).toLowerCase(), combined));
      });
    } catch {
      // Optional examples must never block the private resource dashboard.
      state.providerProfiles.clear();
    }
  }

  function viewRegistry() {
    return viewModules;
  }

  function updateNav() {
    const group = ["recommended", "token", "gpu", "grant"].includes(state.currentView)
      ? "resources"
      : ["token-prices", "gpu-prices"].includes(state.currentView)
        ? "pricing"
        : state.currentView;
    dom.tabs.forEach((tab) => {
      const active = tab.dataset.viewGroup
        ? tab.dataset.viewGroup === group
        : tab.dataset.view === state.currentView;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-current", active ? "page" : "false");
    });
  }

  function catalogLabel() {
    return state.currentView === "token-prices"
      ? "Token 费用榜单"
      : state.currentView === "gpu-prices"
        ? "GPU 算力费用榜单"
        : state.currentView === "tips"
          ? "AI 效率技巧"
          : state.currentView === "changes"
            ? "变化记录"
            : state.currentView === "recommended"
              ? "按用途浏览"
              : `${kindLabel(state.currentView)}资源`;
  }

  function syncViewShell() {
    const priceView = ["token-prices", "gpu-prices"].includes(state.currentView);
    const changes = state.currentView === "changes";
    const tips = state.currentView === "tips";
    const resourceView = ["recommended", "token", "gpu", "grant"].includes(state.currentView);
    updateHero(ctx);
    updateNav();
    dom.viewSubnav.hidden = !(resourceView || priceView);
    dom.resourceSubnav.hidden = !resourceView;
    dom.priceSubnav.hidden = !priceView;
    dom.freeQuickFilters.hidden = priceView || changes || tips;
    dom.heroTrust.hidden = !resourceView;
    dom.featuredSection.hidden = state.currentView !== "recommended";
    dom.summaryRoot.hidden = priceView || changes || tips;
    dom.pricingControls.hidden = !priceView;
    dom.browserGrid.classList.toggle("pricing-mode", priceView || tips);
    dom.radarSidebar.hidden = priceView || tips;
    dom.filters.hidden = changes || priceView || tips || dom.filterToggle.getAttribute("aria-expanded") !== "true";
    dom.filterToggle.hidden = changes || priceView || tips;
    dom.queryInput.disabled = changes;
    dom.catalogTitle.textContent = catalogLabel();
    if (priceView) configurePricingControls(ctx);
    if (state.pendingRouteFilters) {
      if (priceView) applyPricingRouteFilters(state.pendingRouteFilters);
      state.pendingRouteFilters = null;
    }
  }

  function loadCurrentView() {
    beginViewRequest();
    syncViewShell();
    syncRoute();
    dom.resultsRoot.setAttribute("aria-busy", "true");
    const registry = viewRegistry();
    const module = registry[state.currentView] || registry.resources;
    if (module?.section) document.querySelector(".catalog-section")?.setAttribute("data-section", module.section);
    let task;
    if (state.currentView === "recommended") task = registry.resources?.loadResources?.(ctx);
    else if (["token", "gpu", "grant"].includes(state.currentView)) task = module?.loadResources?.(ctx);
    else if (state.currentView === "token-prices") task = module?.loadTokenPrices?.(ctx);
    else if (state.currentView === "gpu-prices") task = module?.loadGpuPrices?.(ctx);
    else if (state.currentView === "tips") task = module?.loadTips?.(ctx);
    else if (state.currentView === "changes") task = module?.loadChanges?.(ctx);
    Promise.resolve(task).finally(() => {
      if (dom.resultsRoot) dom.resultsRoot.setAttribute("aria-busy", "false");
    });
  }

  function selectView(view) {
    if (!KNOWN_VIEWS.has(view)) return;
    state.currentView = view;
    state.pendingRouteFilters = null;
    loadCurrentView();
    if (view !== "recommended") {
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      document.querySelector(".catalog-section")?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    }
  }

  async function pollRefresh() {
    try {
      const refresh = await fetchJson("/api/ai-resources/refresh");
      dom.refreshState.hidden = false;
      if (refresh.status === "running") {
        dom.refreshState.textContent = `正在核验官方来源 · 开始于 ${formatTime(refresh.started_at)}`;
        state.refreshTimer = window.setTimeout(pollRefresh, 1200);
        return;
      }
      dom.refreshButton.disabled = false;
      dom.refreshState.textContent = refresh.status === "completed"
        ? "核验完成，资源列表和变化记录已更新。"
        : refresh.status === "partial"
          ? "核验完成，但部分来源需要稍后重试或人工复核。"
          : "核验任务未能完成，请查看来源状态。";
      await Promise.all([registryRecommended(), Promise.resolve(loadCurrentView())]);
    } catch {
      dom.refreshButton.disabled = false;
      dom.refreshState.hidden = false;
      dom.refreshState.textContent = "无法读取刷新状态。";
    }
  }

  function registryRecommended() {
    return viewRegistry().recommended?.loadDashboard?.(ctx);
  }

  dom.refreshButton.addEventListener("click", async () => {
    dom.refreshButton.disabled = true;
    dom.refreshState.hidden = false;
    dom.refreshState.textContent = "正在启动核验任务…";
    try {
      await fetchJson("/api/ai-resources/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force: true }) });
      pollRefresh();
    } catch (error) {
      dom.refreshButton.disabled = false;
      dom.refreshState.textContent = error.message === "ai_radar_refresh_already_running" ? "已有核验任务在运行。" : "无法启动核验任务。";
    }
  });

  dom.tabs.forEach((tab) => tab.addEventListener("click", () => selectView(tab.dataset.view)));
  document.querySelectorAll("[data-open-view]").forEach((link) => link.addEventListener("click", () => selectView(link.dataset.openView)));
  [dom.verifiedOnly, dom.noCard, dom.freeImageGeneration, dom.mainlandSupported, dom.mainlandUnknown, dom.mainlandUnsupported]
    .forEach((control) => control.addEventListener("change", loadCurrentView));
  dom.queryInput.addEventListener("input", () => {
    syncRoute();
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(loadCurrentView, 250);
  });
  [dom.pricingSort, dom.pricingDirection, dom.pricingProvider, dom.tokenVerification, dom.tokenMinContext,
    dom.tokenMaxTypical, dom.tokenMaxInput, dom.tokenMaxOutput, dom.tokenCache, dom.gpuModel, dom.gpuMinVram,
    dom.gpuMaxHourly, dom.gpuBilling, dom.gpuTier, dom.gpuPriceMode, dom.gpuHours]
    .forEach((control) => control.addEventListener("change", loadCurrentView));
  document.querySelector("#reset-pricing-filters").addEventListener("click", () => {
    dom.queryInput.value = "";
    dom.pricingProvider.value = "";
    dom.pricingDirection.value = "asc";
    dom.tokenVerification.value = "all";
    dom.tokenMinContext.value = "";
    dom.tokenMaxTypical.value = "";
    dom.tokenMaxInput.value = "";
    dom.tokenMaxOutput.value = "";
    dom.tokenCache.value = "any";
    dom.gpuModel.value = "";
    dom.gpuMinVram.value = "";
    dom.gpuMaxHourly.value = "";
    dom.gpuBilling.value = "";
    dom.gpuTier.value = "";
    dom.gpuPriceMode.value = "all";
    dom.gpuHours.value = "10";
    dom.pricingSort.value = state.currentView === "token-prices" ? "typical" : "hourly";
    loadCurrentView();
  });
  dom.togglePriceFilters.addEventListener("click", () => {
    const expanded = dom.togglePriceFilters.getAttribute("aria-expanded") === "true";
    dom.togglePriceFilters.setAttribute("aria-expanded", String(!expanded));
    dom.pricingAdvanced.hidden = expanded;
    dom.togglePriceFilters.textContent = expanded ? "展开高级筛选" : "收起高级筛选";
    syncRoute();
  });
  dom.sourceHealthDisclosure.addEventListener("toggle", () => {
    const hint = dom.sourceHealthDisclosure.querySelector(".disclosure-hint");
    if (hint) hint.textContent = dom.sourceHealthDisclosure.open ? "收起" : "展开";
  });
  dom.filterToggle.addEventListener("click", () => {
    const expanded = dom.filterToggle.getAttribute("aria-expanded") === "true";
    dom.filterToggle.setAttribute("aria-expanded", String(!expanded));
    dom.filters.hidden = expanded;
  });
  document.querySelector("#show-all-resources").addEventListener("click", () => {
    dom.verifiedOnly.checked = false;
    dom.noCard.checked = false;
    dom.freeImageGeneration.checked = false;
    dom.mainlandSupported.checked = true;
    dom.mainlandUnknown.checked = true;
    dom.mainlandUnsupported.checked = true;
    dom.filterToggle.setAttribute("aria-expanded", "true");
    dom.filters.hidden = false;
    selectView("recommended");
  });
  document.querySelector("#ranking-explainer").addEventListener("click", (event) => renderRankingExplainer(ctx, event.currentTarget));
  document.querySelector("#pricing-method").addEventListener("click", (event) => renderPricingMethod(ctx, event.currentTarget));
  document.querySelector("#clear-price-compare").addEventListener("click", () => {
    state.comparedPrices.clear();
    updateCompareBar(ctx);
    loadCurrentView();
  });
  dom.openPriceCompare.addEventListener("click", (event) => renderComparison(ctx, event.currentTarget));
  dom.closeDialogButton.addEventListener("click", () => dialogController.close());
  dom.dialog.addEventListener("click", (event) => {
    if (event.target === dom.dialog) dialogController.close();
  });

  function restoreRoute() {
    const next = readRoute();
    state.currentView = next.view;
    dom.queryInput.value = next.query;
    state.tipFilters = {
      status: next.filters.tip_status || "",
      category: next.filters.tip_category || "",
      risk: next.filters.tip_risk || "",
      source: next.filters.tip_source || "",
      scope: next.filters.tip_scope || "",
    };
    state.pendingRouteFilters = next.filters;
    applyBaseRouteFilters(next.filters);
    loadCurrentView();
  }

  window.addEventListener("hashchange", restoreRoute);
  window.addEventListener("popstate", restoreRoute);

  Promise.all([loadProviderProfiles(), registryRecommended(), Promise.resolve(loadCurrentView())]);
}
