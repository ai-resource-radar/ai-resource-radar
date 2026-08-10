/* AI productivity tips review and import view. */
import { formatTime } from "/ai-radar-assets/modules/formatters.js";
import { activateCard, element, metric, safeLink } from "/ai-radar-assets/modules/components.js";

export const viewId = "tips";
export const section = "工具";

const tipCategoryLabels = {
  delegation: "委派协作", prompting: "提示词", context: "上下文",
  verification: "测试验证", cost: "成本控制", security: "安全",
};

function tipStatusLabel(value) {
  return { candidate: "待审核", approved: "已批准", rejected: "已拒绝", retired: "已撤回" }[value] || value;
}

async function reviewTip(tipId, action, scope, ctx) {
  try {
    await ctx.fetchJson(`/api/ai-tips/${encodeURIComponent(tipId)}/review`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action, ...(scope ? { scope } : {}) }),
    });
    ctx.dialog.close();
    ctx.beginViewRequest();
    await loadTips(ctx);
  } catch (error) {
    ctx.dom.detailRoot.append(element("p", "tip-error", `操作失败：${error.message}`));
  }
}

function openTip(tip, trigger, ctx) {
  ctx.dom.detailRoot.replaceChildren(
    element("span", "tip-status", `${tipStatusLabel(tip.status)} · ${tipCategoryLabels[tip.category] || tip.category}`),
    element("h2", "", tip.title),
    element("p", "offer-provider", tip.summary),
  );
  const instruction = element("section", "policy-note");
  instruction.append(element("strong", "", "具体做法"), element("p", "", tip.instruction));
  ctx.dom.detailRoot.append(instruction);
  if (tip.example) {
    const example = element("section", "policy-note");
    example.append(element("strong", "", "示例"), element("p", "", tip.example));
    ctx.dom.detailRoot.append(example);
  }
  if (Array.isArray(tip.constraints) && tip.constraints.length) {
    const limits = element("section", "evidence-box");
    limits.append(element("strong", "", "边界与风险"));
    tip.constraints.forEach((item) => limits.append(element("p", "", `• ${item}`)));
    ctx.dom.detailRoot.append(limits);
  }
  const evidence = element("section", "policy-note");
  evidence.append(element("strong", "", tip.source_type === "official" ? "官方证据" : "手动来源"));
  evidence.append(element("p", "", tip.evidence_summary || "仅保存结构化摘要，原文需通过来源链接复核。"));
  const link = safeLink("查看来源 ↗", tip.source_url, "price-source-link");
  if (link) evidence.append(link);
  ctx.dom.detailRoot.append(evidence);
  if (tip.status === "candidate") {
    const actions = element("div", "tip-review-actions");
    [["global", "批准并应用到全局"], ["project", "应用到当前项目"], ["both", "同时应用"]].forEach(([scope, label]) => {
      const button = element("button", "tip-approve", label);
      button.type = "button";
      button.addEventListener("click", () => reviewTip(tip.tip_id, "approve", scope, ctx));
      actions.append(button);
    });
    const reject = element("button", "tip-reject", "拒绝候选");
    reject.type = "button";
    reject.addEventListener("click", () => reviewTip(tip.tip_id, "reject", "", ctx));
    actions.append(reject);
    ctx.dom.detailRoot.append(actions);
  }
  ctx.openDialog(trigger);
}

function tipCard(tip, ctx) {
  const card = element("article", "tip-card");
  card.append(
    element("span", `tip-status ${tip.status}`, `${tipStatusLabel(tip.status)} · ${tipCategoryLabels[tip.category] || tip.category}`),
    element("h3", "", tip.title),
    element("p", "", tip.summary),
    element("small", "", `${tip.source_type === "official" ? "官方来源" : "手动导入"} · 风险 ${tip.risk_level}`),
  );
  activateCard(card, (trigger) => openTip(tip, trigger, ctx));
  return card;
}

function tipFilterSelect(label, key, options, ctx) {
  const wrapper = element("label", "tip-filter");
  wrapper.append(element("span", "", label));
  const select = element("select");
  options.forEach(([value, text]) => select.append(new Option(text, value)));
  select.value = ctx.state.tipFilters[key];
  select.addEventListener("change", () => {
    ctx.state.tipFilters[key] = select.value;
    ctx.syncRoute();
    ctx.beginViewRequest();
    loadTips(ctx);
  });
  wrapper.append(select);
  return wrapper;
}

function tipImportField(label, name, { multiline = false, type = "text" } = {}) {
  const wrapper = element("label", "tip-import-field");
  wrapper.append(element("span", "", label));
  const input = element(multiline ? "textarea" : "input");
  input.name = name;
  if (!multiline) input.type = type;
  input.required = true;
  wrapper.append(input);
  return [wrapper, input];
}

function openTipImport(event, ctx) {
  ctx.dom.detailRoot.replaceChildren(element("h2", "", "手动导入效率技巧"), element("p", "offer-provider", "只保存结构化摘要，不抓取或归档完整网页；导入后仍需人工批准。"));
  const form = element("form", "tip-import-form");
  const [urlField, url] = tipImportField("来源 HTTPS URL", "source_url", { type: "url" });
  const [titleField, title] = tipImportField("标题", "title");
  const categoryField = element("label", "tip-import-field");
  categoryField.append(element("span", "", "分类"));
  const category = element("select");
  Object.entries(tipCategoryLabels).forEach(([value, label]) => category.append(new Option(label, value)));
  categoryField.append(category);
  const [summaryField, summary] = tipImportField("短摘要", "summary", { multiline: true });
  const [instructionField, instruction] = tipImportField("审核后将写入的具体做法", "instruction", { multiline: true });
  const [exampleField, example] = tipImportField("示例", "example", { multiline: true });
  example.required = false;
  const submit = element("button", "tip-approve", "保存为待审核候选");
  submit.type = "submit";
  form.append(urlField, titleField, categoryField, summaryField, instructionField, exampleField, submit);
  form.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    submit.disabled = true;
    try {
      await ctx.fetchJson("/api/ai-tips/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_url: url.value, title: title.value, category: category.value, summary: summary.value, instruction: instruction.value, example: example.value, source_type: "manual", risk_level: "medium" }),
      });
      ctx.dialog.close();
      ctx.beginViewRequest();
      await loadTips(ctx);
    } catch (error) {
      submit.disabled = false;
      form.append(element("p", "tip-error", `导入失败：${error.message}`));
    }
  });
  ctx.dom.detailRoot.append(form);
  ctx.openDialog(event?.currentTarget);
}

async function rollbackTip(applicationId, ctx) {
  await ctx.fetchJson(`/api/ai-tips/applications/${applicationId}/rollback`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  ctx.beginViewRequest();
  await loadTips(ctx);
}

export async function loadTips(ctx) {
  ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在读取效率技巧…"));
  try {
    const parameters = new URLSearchParams({ limit: "200" });
    if (ctx.dom.queryInput.value.trim()) parameters.set("q", ctx.dom.queryInput.value.trim());
    Object.entries(ctx.state.tipFilters).forEach(([key, value]) => { if (value) parameters.set(key, value); });
    const [summary, payload, applications] = await Promise.all([
      ctx.fetchViewJson("/api/ai-tips/summary"),
      ctx.fetchViewJson(`/api/ai-tips?${parameters}`),
      ctx.fetchViewJson("/api/ai-tips/applications?limit=20"),
    ]);
    const root = element("div", "tips-workspace");
    const controls = element("div", "tip-filter-bar");
    controls.append(
      tipFilterSelect("状态", "status", [["", "全部"], ["candidate", "待审核"], ["approved", "已批准"], ["rejected", "已拒绝"], ["retired", "已撤回"]], ctx),
      tipFilterSelect("分类", "category", [["", "全部"], ["delegation", "委派协作"], ["prompting", "提示词"], ["context", "上下文"], ["verification", "测试验证"], ["cost", "成本控制"], ["security", "安全"]], ctx),
      tipFilterSelect("风险", "risk", [["", "全部"], ["low", "低"], ["medium", "中"], ["high", "高"]], ctx),
      tipFilterSelect("来源", "source", [["", "全部"], ["official", "官方"], ["manual", "手动"], ["community", "社区"]], ctx),
      tipFilterSelect("范围", "scope", [["", "全部"], ["global", "全局"], ["project", "项目"]], ctx),
    );
    const importButton = element("button", "tip-import-open", "手动导入");
    importButton.type = "button";
    importButton.addEventListener("click", (event) => openTipImport(event, ctx));
    const refreshTipsButton = element("button", "tip-refresh", "核验官方来源");
    refreshTipsButton.type = "button";
    refreshTipsButton.addEventListener("click", async () => {
      refreshTipsButton.disabled = true;
      refreshTipsButton.textContent = "核验中…";
      try { await ctx.fetchJson("/api/ai-tips/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"force":true}' }); } catch { /* status is persisted */ }
      ctx.beginViewRequest();
      await loadTips(ctx);
    });
    controls.append(importButton, refreshTipsButton);
    root.append(controls);
    const overview = element("div", "tips-overview");
    overview.append(metric("待审核", summary.counts.candidate || 0, "不会自动生效"), metric("已批准", summary.counts.approved || 0, "已进入受管规则"), metric("全局应用", summary.applied.global || 0, "影响之后的新任务"), metric("项目应用", summary.applied.project || 0, "只影响当前仓库"));
    root.append(overview);
    root.append(element("p", summary.sources.failed ? "tip-source-state unhealthy" : "tip-source-state", `官方技巧来源：${summary.sources.healthy}/${summary.sources.total} 新鲜${summary.sources.failed ? ` · ${summary.sources.failed} 个需要复核` : ""}`));
    const grid = element("div", "tip-grid");
    if (payload.tips.length) grid.append(...payload.tips.map((tip) => tipCard(tip, ctx)));
    else grid.append(element("div", "radar-empty", "没有符合条件的技巧。"));
    root.append(grid);
    if (applications.applications.length) {
      const audit = element("section", "tip-audit");
      audit.append(element("h3", "", "最近规则应用"));
      applications.applications.forEach((item) => {
        const row = element("div", "tip-audit-row");
        row.append(element("span", "", `${item.scope === "global" ? "全局" : "项目"} · ${item.title}`), element("small", "", `${item.status} · ${formatTime(item.applied_at)}`));
        if (item.status === "applied") {
          const button = element("button", "tip-rollback", "回滚");
          button.type = "button";
          button.addEventListener("click", () => rollbackTip(item.id, ctx).catch(() => {}));
          row.append(button);
        }
        audit.append(row);
      });
      root.append(audit);
    }
    ctx.dom.catalogCaption.textContent = `共 ${payload.count} 条；全部需要人工审核`;
    ctx.dom.resultsRoot.replaceChildren(root);
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 AI 效率技巧。"));
  }
}
