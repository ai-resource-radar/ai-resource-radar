/* Resource catalogue view. */
import { actionQuota, benefitSummary, guide, kindLabel, usageSteps } from "/ai-radar-assets/modules/formatters.js";
import { element, providerInitials, safeLink } from "/ai-radar-assets/modules/components.js";

export const viewId = "resources";
export const section = "发现资源";

function mainlandValues(ctx) {
  const values = [];
  if (ctx.dom.mainlandSupported.checked) values.push("supported");
  if (ctx.dom.mainlandUnknown.checked) values.push("unknown");
  if (ctx.dom.mainlandUnsupported.checked) values.push("unsupported");
  return values;
}

function resourceQuery(ctx) {
  const parameters = new URLSearchParams({ limit: "200" });
  if (ctx.state.currentView !== "recommended") parameters.set("kind", ctx.state.currentView);
  if (ctx.dom.verifiedOnly.checked) parameters.set("verified", "true");
  if (ctx.dom.noCard.checked) parameters.set("no_card", "true");
  if (ctx.dom.freeImageGeneration.checked) parameters.set("free_image_generation", "true");
  const mainland = mainlandValues(ctx);
  if (mainland.length) parameters.set("mainland", mainland.join(","));
  if (ctx.dom.queryInput.value.trim()) parameters.set("q", ctx.dom.queryInput.value.trim());
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

function providerRow(resources, ctx) {
  const representative = resources[0];
  const row = element("article", "provider-row");
  const title = element("div", "provider-title");
  const copy = element("div");
  copy.append(element("strong", "", representative.provider), element("small", "", resources.length > 1 ? `${resources.length} 个免费模型 · 共享同一免费政策` : `${kindLabel(representative.kind)} · ${representative.title}`));
  title.append(element("span", "provider-icon", providerInitials(representative.provider)), copy);
  const quota = element("div", "provider-quota");
  quota.append(element("strong", "", actionQuota(representative)), element("small", "", benefitSummary(representative)));
  const guideAction = element("div", "provider-guide-action");
  const steps = usageSteps(representative);
  const claim = safeLink("去领取 ↗", guide(representative).action_url || representative.homepage_url, "provider-claim");
  const details = element("button", "provider-details", resources.length > 1 ? `查看 ${resources.length} 项` : "查看步骤");
  details.type = "button";
  details.addEventListener("click", () => resources.length === 1
    ? ctx.showOffer(representative, details)
    : ctx.showProvider(resources, details));
  guideAction.append(element("small", "", steps.length ? `${steps.length} 步开始使用` : "查看领取条件"));
  if (claim) guideAction.append(claim);
  guideAction.append(details);
  row.append(title, quota, guideAction);
  return row;
}

export async function loadResources(ctx) {
  ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在筛选本地资源…"));
  try {
    const payload = await ctx.fetchViewJson(`/api/ai-resources?${resourceQuery(ctx)}`);
    if (!payload.resources.length) {
      ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "当前条件下没有资源，可以打开“更多筛选”放宽条件。"));
      ctx.dom.catalogCaption.textContent = "当前条件下没有匹配结果";
      return;
    }
    const groups = groupResources(payload.resources);
    ctx.dom.catalogCaption.textContent = `${payload.resources.length} 项资源，已聚合为 ${groups.length} 个供应商`;
    ctx.dom.resultsRoot.replaceChildren(...groups.map((group) => providerRow(group, ctx)));
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取 AI 资源库。"));
  }
}
