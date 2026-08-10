/* DOM components stay text-only so source data can never become markup. */
import { createDialogController } from "/ai-radar-assets/ui-modules.js";
import { createOfferCard } from "/ai-radar-shared/cards.js";
import { element, safeLink } from "/ai-radar-shared/dom.js";
import {
  actionQuota,
  benefitSummary,
  caveats,
  formatTime,
  guide,
  kindLabel,
  resetLabel,
  usageSteps,
} from "/ai-radar-assets/modules/formatters.js";

export { element, safeLink };

export function metric(label, value, note) {
  const card = element("article", "radar-metric");
  card.append(element("span", "", label), element("strong", "", value), element("small", "", note));
  return card;
}

export function providerInitials(provider) {
  const overrides = {
    OpenRouter: "OR", Groq: "GQ", Cloudflare: "CF", "Google Gemini": "GM",
    "Google Colab": "GC", "Hugging Face": "HF", "Lightning AI": "LI",
    Modal: "MO", Kaggle: "KG",
  };
  if (overrides[provider]) return overrides[provider];
  return provider.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "AI";
}

export function replaceSelectOptions(select, values, allLabel) {
  const selected = select.value;
  select.replaceChildren(new Option(allLabel, ""));
  values.forEach((value) => select.append(new Option(value, value)));
  if ([...select.options].some((option) => option.value === selected)) select.value = selected;
}

export function installDialog(dialog, closeButton, detailRoot) {
  return createDialogController(dialog, closeButton, detailRoot);
}

export function cardBadges(resource) {
  const badges = [[resource.requires_card === "no" ? "无需信用卡" : "信用卡待确认", ""]];
  if (resource.free_image_generation) badges.push(["免费生图", "good"]);
  if (resource.reset_period && !["unknown", "variable"].includes(resource.reset_period)) {
    badges.push([`${resetLabel(resource.reset_period)}重置`, ""]);
  }
  badges.push(resource.mainland_status === "supported"
    ? ["大陆可用", "good"]
    : resource.mainland_status === "unsupported" ? ["大陆不支持", ""] : ["大陆待确认", ""]);
  return badges;
}

export function activateCard(card, action) {
  card.setAttribute("role", "button");
  card.setAttribute("aria-haspopup", "dialog");
  card.tabIndex = 0;
  card.addEventListener("click", () => action(card));
  card.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key)) return;
    event.preventDefault();
    action(card);
  });
}

export function featureCard(resource, primary, ctx) {
  return createOfferCard(resource, {
    locale: "zh-CN",
    primary,
    className: "feature-card",
    onDetails: (offer, trigger) => ctx.showOffer(offer, trigger),
  });
}

function appendPolicyGuide(resource, detailRoot, options = {}) {
  const resourceGuide = guide(resource);
  const policy = element("section", "policy-hero");
  policy.append(element("span", "policy-kicker", "你能白嫖到"), element("strong", "policy-amount", actionQuota(resource)), element("p", "policy-summary", benefitSummary(resource)));
  const badges = element("div", "offer-badges");
  cardBadges(resource).forEach(([text, className]) => badges.append(element("span", className, text)));
  policy.append(badges);
  detailRoot.append(policy);
  const grid = element("div", "detail-grid compact");
  [["恢复周期", resetLabel(resource.reset_period)], ["信用卡", resource.requires_card === "no" ? "不需要" : resource.requires_card === "yes" ? "需要" : "待确认"], ["大陆情况", resource.mainland_status === "supported" ? "可用" : resource.mainland_status === "unsupported" ? "官方不支持" : "待确认"], ["最近核验", formatTime(resource.last_seen_at)]].forEach(([label, value]) => {
    const item = element("div");
    item.append(element("span", "", label), element("strong", "", value));
    grid.append(item);
  });
  detailRoot.append(grid);
  if (!options.hideActions) {
    const actions = element("div", "policy-actions");
    const primary = safeLink(resourceGuide.action_label || "去使用", resourceGuide.action_url || resource.homepage_url, "policy-primary-action");
    const source = safeLink("查看官方政策 ↗", resource.homepage_url, "policy-secondary-action");
    if (primary) actions.append(primary);
    if (source && (!primary || source.href !== primary.href)) actions.append(source);
    if (actions.childElementCount) detailRoot.append(actions);
  }
  const steps = usageSteps(resource);
  if (steps.length) {
    const section = element("section", "guide-section");
    section.append(element("span", "guide-eyebrow", `怎么操作 · ${steps.length} 步`), element("h3", "", "照着做就能开始用"));
    const list = element("ol", "policy-steps");
    steps.forEach((step) => list.append(element("li", "", step)));
    section.append(list);
    detailRoot.append(section);
  }
  if (resourceGuide.best_for) {
    const best = element("section", "policy-note best-for");
    best.append(element("strong", "", "适合做什么"), element("p", "", resourceGuide.best_for));
    detailRoot.append(best);
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
}

function appendIntegrationExamples(resource, detailRoot, ctx) {
  const profile = ctx.state.providerProfiles?.get(String(resource.provider || "").toLowerCase());
  const templates = profile?.integration?.templates;
  if (!templates || !Object.keys(templates).length) return;
  const disclosure = element("details", "integration-disclosure");
  disclosure.append(element("summary", "", "接入示例 · curl / Python / 编程工具"));
  const intro = element("p", "offer-provider", "只展示经过协议门禁的确定性模板。密钥请放在对应环境变量中，页面不会读取或保存。 ");
  disclosure.append(intro);
  const labels = { curl: "curl", python: "Python", openclaw: "OpenClaw", cursor: "Cursor", codex: "Codex" };
  Object.entries(templates).forEach(([client, snippet]) => {
    const block = element("section", "integration-snippet");
    const heading = element("div", "integration-snippet-heading");
    heading.append(element("strong", "", labels[client] || client));
    const copy = element("button", "", "复制");
    copy.type = "button";
    const pre = element("pre", "");
    const code = element("code", "", snippet);
    pre.append(code);
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.textContent || "");
        copy.textContent = "已复制";
        window.setTimeout(() => { copy.textContent = "复制"; }, 1400);
      } catch {
        pre.focus();
      }
    });
    heading.append(copy);
    block.append(heading, pre);
    disclosure.append(block);
  });
  detailRoot.append(disclosure);
}

export function createDialogActions({ dialog, detailRoot, dialogController, ctx }) {
  function openDialog(trigger) { dialogController.open(trigger); }
  function showOffer(resource, trigger) {
    detailRoot.replaceChildren();
    const tier = element("span", "tier", resource.priority_tier);
    tier.dataset.tier = resource.priority_tier;
    const copy = element("div");
    copy.append(element("h2", "", resource.title), element("p", "offer-provider", resource.provider));
    const heading = element("div", "offer-heading");
    heading.append(tier, copy);
    detailRoot.append(heading);
    appendPolicyGuide(resource, detailRoot);
    const disclosure = element("details", "evidence-disclosure");
    disclosure.append(element("summary", "", "查看官方核验依据与排序原因"));
    const reasons = element("div", "evidence-box");
    (resource.priority_reasons || []).forEach((reason) => reasons.append(element("p", "", `• ${reason}`)));
    if (resource.evidence) reasons.append(element("span", "evidence-label", "来源摘录"), element("p", "", resource.evidence.evidence_excerpt || "来源已记录"));
    disclosure.append(reasons);
    detailRoot.append(disclosure);
    appendIntegrationExamples(resource, detailRoot, ctx);
    openDialog(trigger);
  }
  function showProvider(resources, trigger) {
    detailRoot.replaceChildren();
    const provider = resources[0].provider;
    const heading = element("div", "offer-heading");
    heading.append(element("span", "tier", providerInitials(provider)), element("div", ""));
    const copy = heading.lastElementChild;
    copy.append(element("h2", "", provider), element("p", "offer-provider", `${resources.length} 项官方免费资源，共用下面这套领取方式`));
    detailRoot.append(heading);
    appendPolicyGuide(resources[0], detailRoot);
    const modelHeading = element("div", "provider-list-heading");
    modelHeading.append(element("h3", "", `可用资源（${resources.length}）`), element("span", "", "点开可查看模型参数与单项证据"));
    const list = element("div", "provider-dialog-list");
    resources.forEach((resource) => {
      const button = element("button", "provider-dialog-item");
      button.type = "button";
      const copy = element("span");
      copy.append(element("strong", "", resource.title), element("small", "", `${kindLabel(resource.kind)} · ${actionQuota(resource)}`));
      button.append(copy, element("span", "provider-arrow", "›"));
      button.addEventListener("click", () => showOffer(resource, button));
      list.append(button);
    });
    detailRoot.append(modelHeading, list);
    appendIntegrationExamples(resources[0], detailRoot, ctx);
    openDialog(trigger);
  }
  return { openDialog, showOffer, showProvider };
}

export function updateHero(ctx) {
  const { currentView } = ctx.state;
  ctx.dom.queryInput.placeholder = currentView === "tips" ? "搜索技巧" : "搜索资源";
  if (currentView === "tips") {
    ctx.dom.heroEyebrow.textContent = "AI PRODUCTIVITY PLAYBOOK";
    ctx.dom.heroTitle.replaceChildren("把好方法，", element("br"), "变成可复用规则");
    ctx.dom.heroCopy.textContent = "官方技巧和手动导入内容先进入候选库。只有人工批准后，才会写入受管 AGENTS.md 区块并影响之后的新任务。";
    ctx.dom.heroPickLabel.textContent = "安全原则";
    ctx.dom.heroPickTitle.textContent = "先审核，再吸收";
    ctx.dom.heroPickNote.textContent = "每次写入均备份、记录哈希并支持回滚";
  } else if (currentView === "poster") {
    ctx.dom.heroEyebrow.textContent = "AI-GENERATED DAILY POSTER";
    ctx.dom.heroTitle.replaceChildren("每天一张，", element("br"), "AI 资源情报海报");
    ctx.dom.heroCopy.textContent = "海报由图片模型整张生成，再由本机 OCR 核对服务商、免费额度和价格数字。校验不通过就不会发布。";
    ctx.dom.heroPickLabel.textContent = "质量控制";
    ctx.dom.heroPickTitle.textContent = "最多 3 次 · 严格校验";
    ctx.dom.heroPickNote.textContent = "图片失败不会影响资源雷达和昨日海报";
  } else if (currentView === "token-prices") {
    ctx.dom.heroEyebrow.textContent = "TOKEN PRICE LEADERBOARD";
    ctx.dom.heroTitle.replaceChildren("Token 费用，", element("br"), "谁更便宜？");
    ctx.dom.heroCopy.textContent = "输入、输出、缓存和上下文分别比较，再用公开公式估算典型任务成本。原价和核验级别不会被综合分隐藏。";
    ctx.dom.heroPickLabel.textContent = "默认比较口径";
    ctx.dom.heroPickTitle.textContent = "1M 输入 + 250K 输出";
    ctx.dom.heroPickNote.textContent = "可切换按输入价、输出价或上下文排序";
  } else if (currentView === "gpu-prices") {
    ctx.dom.heroEyebrow.textContent = "GPU COMPUTE LEADERBOARD";
    ctx.dom.heroTitle.replaceChildren("同一块 GPU，", element("br"), "哪里租更省？");
    ctx.dom.heroCopy.textContent = "统一换算成单 GPU 每小时费用，同时展示显存、计费模式和任务成本。实时市场价与固定按需价分开标识。";
    ctx.dom.heroPickLabel.textContent = "默认比较口径";
    ctx.dom.heroPickTitle.textContent = "单 GPU · USD / 小时";
    ctx.dom.heroPickNote.textContent = "不包含存储、网络、税费和长期合约折扣";
  } else {
    ctx.dom.heroEyebrow.textContent = "VERIFIED FREE AI · UPDATED DAILY";
    ctx.dom.heroTitle.textContent = "今天有哪些真正能领的免费 AI 资源？";
    ctx.dom.heroCopy.textContent = "额度、门槛和领取入口一次看清；每项结论都能回到官方证据。";
    ctx.dom.heroPickLabel.textContent = "今日精选";
  }
}

export function renderRankingExplainer(ctx, trigger) {
  ctx.dom.detailRoot.replaceChildren(
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
  ctx.dom.detailRoot.append(box);
  ctx.openDialog(trigger);
}

export function renderPricingMethod(ctx, trigger) {
  ctx.dom.detailRoot.replaceChildren(
    element("h2", "", "价格榜比较口径"),
    element("p", "offer-provider", "榜单只使用公开字段和明确公式，不生成隐藏综合分。"),
  );
  [
    ["Token", "输入和输出均按美元/百万 Token 展示。典型对话成本 = 100 万输入价格 + 25 万输出价格；缓存费用单独保留，不混入默认公式。"],
    ["GPU", "固定价统一换算为单 GPU 每小时美元价格；任务成本 = 小时价 × 选择的运行时长。显存性价比仅表示美元/GB·小时，不代表训练速度。"],
    ["核验", "官方页面解析结果标为“官方价格”；genai-prices 等成熟目录只标为“社区价格基线”，不会冒充官方核验。"],
    ["未包含", "存储、网络流量、税费、区域差价、批量折扣和预留合约可能改变最终账单，使用前应再次打开价格来源确认。"],
  ].forEach(([title, copy]) => {
    const box = element("section", "policy-note");
    box.append(element("strong", "", title), element("p", "", copy));
    ctx.dom.detailRoot.append(box);
  });
  ctx.openDialog(trigger);
}
