/* Token/GPU price comparison view. */
import {
  compactNumber,
  formatContext,
  formatTime,
  formatUsd,
} from "/ai-radar-assets/modules/formatters.js";
import {
  element,
  replaceSelectOptions,
  safeLink,
} from "/ai-radar-assets/modules/components.js";

export const viewId = "pricing";
export const section = "价格比较";
const PRICE_PAGE_SIZE = 20;

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

export function updateCompareBar(ctx) {
  const count = ctx.state.comparedPrices.size;
  ctx.dom.priceCompareBar.hidden = count === 0;
  ctx.dom.priceCompareCount.textContent = `已选择 ${count} 项${count < 2 ? "，再选一项即可对比" : ""}`;
  ctx.dom.openPriceCompare.disabled = count < 2;
}

function compareToggle(item, kind, ctx) {
  const label = element("label", "price-compare-toggle");
  const checkbox = element("input");
  checkbox.type = "checkbox";
  checkbox.checked = ctx.state.comparedPrices.has(item.price_id);
  checkbox.setAttribute("aria-label", `将 ${item.model || item.title || item.gpu_model} 加入对比`);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked && ctx.state.comparedPrices.size >= 5) {
      checkbox.checked = false;
      ctx.dom.refreshState.hidden = false;
      ctx.dom.refreshState.textContent = "一次最多对比 5 项价格。";
      return;
    }
    if (checkbox.checked) ctx.state.comparedPrices.set(item.price_id, { ...item, price_kind: kind });
    else ctx.state.comparedPrices.delete(item.price_id);
    updateCompareBar(ctx);
  });
  label.append(checkbox, element("span", "", "对比"));
  return label;
}

function tokenPriceRow(item, index, ctx) {
  const row = element("article", "price-row token-price-row");
  const identity = element("div", "price-identity");
  identity.append(element("span", "price-rank", String(index + 1)), element("div", ""));
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
    compareToggle(item, "token", ctx),
  );
  return row;
}

function gpuPriceRow(item, index, hours, ctx) {
  const row = element("article", "price-row gpu-price-row");
  const identity = element("div", "price-identity");
  identity.append(element("span", "price-rank", String(index + 1)), element("div", ""));
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
    compareToggle(item, "gpu", ctx),
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

function priceTable(headers, rows, className, ctx) {
  const table = element("div", `price-table ${className}`);
  const head = element("div", "price-table-head");
  headers.forEach((header) => {
    const [label, sortValue] = Array.isArray(header) ? header : [header, null];
    if (!sortValue) {
      head.append(element("span", "", label));
      return;
    }
    const button = element("button", ctx.dom.pricingSort.value === sortValue ? "active" : "", label);
    button.type = "button";
    if (ctx.dom.pricingSort.value === sortValue) {
      button.append(document.createTextNode(ctx.dom.pricingDirection.value === "desc" ? " ↓" : " ↑"));
    }
    button.addEventListener("click", () => {
      if (ctx.dom.pricingSort.value === sortValue) {
        ctx.dom.pricingDirection.value = ctx.dom.pricingDirection.value === "asc" ? "desc" : "asc";
      } else {
        ctx.dom.pricingSort.value = sortValue;
        ctx.dom.pricingDirection.value = ["context", "vram"].includes(sortValue) ? "desc" : "asc";
      }
      ctx.loadCurrentView();
    });
    head.append(button);
  });
  table.append(head, ...rows);
  return table;
}

function appendPricePager(table, payload, offset, loadNext) {
  table.querySelector(".price-load-more-wrap")?.remove();
  const shown = Math.min(payload.total, offset + payload.count);
  if (shown >= payload.total) return;
  const wrap = element("div", "price-load-more-wrap");
  const count = Math.min(PRICE_PAGE_SIZE, payload.total - shown);
  const status = element("span", "", `已显示 ${shown} / ${payload.total} 项`);
  const button = element("button", "price-load-more", `继续加载 ${count} 项`);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "正在加载…";
    try {
      await loadNext(shown);
    } catch {
      button.disabled = false;
      button.textContent = "重试加载";
    }
  });
  wrap.append(status, button);
  table.append(wrap);
}

function renderPricingFilterSummary(ctx, total, values) {
  ctx.dom.pricingFilterSummary.replaceChildren(element("strong", "", `${total} 条结果`));
  values.filter(Boolean).forEach((value) => ctx.dom.pricingFilterSummary.append(element("span", "", value)));
  if (!values.some(Boolean)) ctx.dom.pricingFilterSummary.append(element("small", "", "当前未添加额外筛选"));
}

function selectedText(select) {
  return select.options[select.selectedIndex]?.text || "";
}

function refreshSelectOptions(select, values, emptyLabel) {
  const selected = select.value;
  replaceSelectOptions(select, values, emptyLabel);
  if (selected && [...select.options].some((option) => option.value === selected)) select.value = selected;
}

export async function loadTokenPrices(ctx, { append = false, offset = 0 } = {}) {
  if (!append) ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在计算 Token 价格榜…"));
  const { dom } = ctx;
  const parameters = new URLSearchParams({
    limit: String(PRICE_PAGE_SIZE),
    offset: String(offset),
    sort: dom.pricingSort.value || "typical",
    direction: dom.pricingDirection.value || "asc",
    verification: dom.tokenVerification.value,
    cache: dom.tokenCache.value,
  });
  if (dom.queryInput.value.trim()) parameters.set("q", dom.queryInput.value.trim());
  if (dom.pricingProvider.value) parameters.set("provider", dom.pricingProvider.value);
  if (dom.tokenMinContext.value) parameters.set("min_context", dom.tokenMinContext.value);
  if (dom.tokenMaxTypical.value) parameters.set("max_typical", dom.tokenMaxTypical.value);
  if (dom.tokenMaxInput.value) parameters.set("max_input", dom.tokenMaxInput.value);
  if (dom.tokenMaxOutput.value) parameters.set("max_output", dom.tokenMaxOutput.value);
  try {
    const payload = await ctx.fetchViewJson(`/api/ai-prices/token?${parameters}`);
    refreshSelectOptions(dom.pricingProvider, payload.providers, "全部供应商");
    dom.catalogCaption.textContent = `${payload.total} 个有标准文本价格的模型`;
    renderPricingFilterSummary(ctx, payload.total, [
      dom.pricingProvider.value && `供应商：${dom.pricingProvider.value}`,
      dom.tokenVerification.value !== "all" && selectedText(dom.tokenVerification),
      dom.tokenMinContext.value && `上下文 ≥ ${selectedText(dom.tokenMinContext).replace("+", "")}`,
      dom.tokenMaxTypical.value && `典型成本 ≤ $${dom.tokenMaxTypical.value}`,
      dom.tokenMaxInput.value && `输入 ≤ $${dom.tokenMaxInput.value}`,
      dom.tokenMaxOutput.value && `输出 ≤ $${dom.tokenMaxOutput.value}`,
      dom.tokenCache.value !== "any" && selectedText(dom.tokenCache),
    ]);
    if (!payload.prices.length) {
      dom.resultsRoot.replaceChildren(element("div", "radar-empty", "当前条件下没有 Token 价格。"));
      return;
    }
    const rows = payload.prices.map((item, index) => tokenPriceRow(item, offset + index, ctx));
    let table = append ? dom.resultsRoot.querySelector(".price-table.token-table") : null;
    if (!table) {
      table = priceTable(
        [["模型 / 供应商", "provider"], ["输入", "input"], ["输出", "output"], ["典型对话", "typical"], ["上下文", "context"], "核验", ""],
        rows,
        "token-table",
        ctx,
      );
      dom.resultsRoot.replaceChildren(
        pricingIntro("默认按典型对话成本排序", "统一假设 100 万输入 Token + 25 万输出 Token；输入、输出原价始终单独展示。", "透明公式"),
        table,
      );
    } else {
      table.querySelector(".price-load-more-wrap")?.remove();
      table.append(...rows);
    }
    appendPricePager(table, payload, offset, (nextOffset) => loadTokenPrices(ctx, { append: true, offset: nextOffset }));
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 Token 价格榜。"));
  }
}

export async function loadGpuPrices(ctx, { append = false, offset = 0 } = {}) {
  if (!append) ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在计算 GPU 算力榜…"));
  const { dom } = ctx;
  const hours = Number(dom.gpuHours.value || 10);
  const parameters = new URLSearchParams({
    limit: String(PRICE_PAGE_SIZE),
    offset: String(offset),
    sort: dom.pricingSort.value || "hourly",
    direction: dom.pricingDirection.value || "asc",
    hours: String(hours),
    price_mode: dom.gpuPriceMode.value,
  });
  if (dom.queryInput.value.trim()) parameters.set("q", dom.queryInput.value.trim());
  if (dom.pricingProvider.value) parameters.set("provider", dom.pricingProvider.value);
  if (dom.gpuModel.value) parameters.set("gpu", dom.gpuModel.value);
  if (dom.gpuMinVram.value) parameters.set("min_vram", dom.gpuMinVram.value);
  if (dom.gpuMaxHourly.value) parameters.set("max_hourly", dom.gpuMaxHourly.value);
  if (dom.gpuBilling.value) parameters.set("billing", dom.gpuBilling.value);
  if (dom.gpuTier.value) parameters.set("tier", dom.gpuTier.value);
  try {
    const payload = await ctx.fetchViewJson(`/api/ai-prices/gpu?${parameters}`);
    refreshSelectOptions(dom.pricingProvider, payload.providers, "全部供应商");
    refreshSelectOptions(dom.gpuModel, payload.gpu_models, "全部型号");
    refreshSelectOptions(dom.gpuBilling, payload.billing_modes, "全部模式");
    refreshSelectOptions(dom.gpuTier, payload.market_tiers, "全部层级");
    dom.catalogCaption.textContent = `${payload.total} 条 GPU 官方价格，按单 GPU 口径比较`;
    renderPricingFilterSummary(ctx, payload.total, [
      dom.pricingProvider.value && `供应商：${dom.pricingProvider.value}`,
      dom.gpuModel.value && `型号：${dom.gpuModel.value}`,
      dom.gpuMinVram.value && `显存 ≥ ${dom.gpuMinVram.value} GB`,
      dom.gpuMaxHourly.value && `小时价 ≤ $${dom.gpuMaxHourly.value}`,
      dom.gpuBilling.value && `计费：${dom.gpuBilling.value}`,
      dom.gpuTier.value && `层级：${dom.gpuTier.value}`,
      dom.gpuPriceMode.value !== "all" && selectedText(dom.gpuPriceMode),
    ]);
    if (!payload.prices.length) {
      dom.resultsRoot.replaceChildren(element("div", "radar-empty", "当前条件下没有 GPU 价格。"));
      return;
    }
    const rows = payload.prices.map((item, index) => gpuPriceRow(item, offset + index, hours, ctx));
    let table = append ? dom.resultsRoot.querySelector(".price-table.gpu-table") : null;
    if (!table) {
      table = priceTable(
        [["GPU / 供应商", "provider"], ["显存", "vram"], ["每小时", "hourly"], [`${hours} 小时`, "hourly"], ["显存性价比", "memory_value"], "核验", ""],
        rows,
        "gpu-table",
        ctx,
      );
      dom.resultsRoot.replaceChildren(
        pricingIntro("同型号、同计费模式下再比较", `小时价统一换算成单 GPU USD；当前任务成本按 ${hours} 小时估算，不包含存储、流量和税费。`, "官方价格"),
        table,
      );
    } else {
      table.querySelector(".price-load-more-wrap")?.remove();
      table.append(...rows);
    }
    appendPricePager(table, payload, offset, (nextOffset) => loadGpuPrices(ctx, { append: true, offset: nextOffset }));
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 GPU 价格榜。"));
  }
}

export function configurePricingControls(ctx) {
  const tokenPrices = ctx.state.currentView === "token-prices";
  if (ctx.dom.pricingControls.dataset.view !== ctx.state.currentView) {
    ctx.dom.pricingControls.dataset.view = ctx.state.currentView;
    ctx.dom.pricingSort.replaceChildren();
    const options = tokenPrices
      ? [["typical", "典型对话成本"], ["input", "输入价格"], ["output", "输出价格"], ["context", "上下文长度"], ["provider", "供应商"]]
      : [["hourly", "每小时价格"], ["memory_value", "显存性价比"], ["vram", "显存大小"], ["provider", "供应商"]];
    options.forEach(([value, label]) => ctx.dom.pricingSort.append(new Option(label, value)));
    replaceSelectOptions(ctx.dom.pricingProvider, [], "全部供应商");
    replaceSelectOptions(ctx.dom.gpuModel, [], "全部型号");
    replaceSelectOptions(ctx.dom.gpuBilling, [], "全部模式");
    replaceSelectOptions(ctx.dom.gpuTier, [], "全部层级");
    ctx.dom.pricingDirection.value = "asc";
    ctx.state.comparedPrices.clear();
    updateCompareBar(ctx);
    ctx.dom.pricingAdvanced.hidden = true;
    ctx.dom.togglePriceFilters.setAttribute("aria-expanded", "false");
    ctx.dom.togglePriceFilters.textContent = "展开高级筛选";
  }
  ctx.dom.tokenPriceControls.forEach((control) => { control.hidden = !tokenPrices; });
  ctx.dom.gpuPriceControls.forEach((control) => { control.hidden = tokenPrices; });
}

export function renderComparison(ctx, trigger) {
  const items = [...ctx.state.comparedPrices.values()];
  if (items.length < 2) return;
  ctx.dom.detailRoot.replaceChildren(
    element("h2", "", items[0].price_kind === "token" ? "Token 价格对比" : "GPU 费用对比"),
    element("p", "offer-provider", `${items.length} 项并排比较；价格来源和核验时间保留。`),
  );
  const grid = element("div", "price-comparison-grid");
  items.forEach((item) => {
    const card = element("article", "price-comparison-card");
    if (item.price_kind === "token") {
      card.append(element("span", "compare-provider", item.provider), element("h3", "", item.model), priceCell("输入 / 百万", formatUsd(item.input_per_mtok)), priceCell("输出 / 百万", formatUsd(item.output_per_mtok)), priceCell("典型对话", formatUsd(item.typical_cost), "1M 输入 + 250K 输出", "highlight"), priceCell("上下文", formatContext(item.context_window)));
    } else {
      card.append(element("span", "compare-provider", item.provider), element("h3", "", item.gpu_model), priceCell("每 GPU 小时", item.hourly_usd === null ? "实时市场价" : formatUsd(item.hourly_usd), item.market_tier, "highlight"), priceCell("显存", item.vram_gb ? `${compactNumber(item.vram_gb)} GB` : "多种型号"), priceCell("任务预估", formatUsd(item.estimated_cost), `${ctx.dom.gpuHours.value} 小时`));
    }
    const link = safeLink("查看价格来源 ↗", item.pricing_url, "price-source-link");
    if (link) card.append(link);
    grid.append(card);
  });
  ctx.dom.detailRoot.append(grid);
  ctx.openDialog(trigger);
}
