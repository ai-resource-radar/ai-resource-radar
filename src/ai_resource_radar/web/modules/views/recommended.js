/* Recommended/dashboard overview view. */
import { featureCard, metric } from "/ai-radar-assets/modules/components.js";
import { formatTime } from "/ai-radar-assets/modules/formatters.js";
import { tr } from "/ai-radar-assets/modules/i18n.js";

export const viewId = "recommended";
export const section = "发现资源";

function chooseFeatured(resources) {
  const choices = [];
  ["Modal", "Cloudflare", "Kaggle"].forEach((provider) => {
    const match = resources.find((resource) => resource.provider === provider && resource.kind !== "grant");
    if (match) choices.push(match);
  });
  resources.filter((resource) => ["A", "B"].includes(resource.priority_tier)).forEach((resource) => {
    if (choices.length < 3 && !choices.some((item) => item.provider === resource.provider)) choices.push(resource);
  });
  return choices.slice(0, 3);
}

export function renderFeatured(ctx, resources) {
  const featured = chooseFeatured(resources);
  if (!featured.length) {
    ctx.dom.featuredRoot.replaceChildren(ctx.element("div", "radar-empty", tr("No officially verified recommendations yet.", "还没有可推荐的官方免费资源。")));
    if (ctx.state.currentView === "recommended") {
      ctx.dom.heroPickTitle.textContent = tr("Waiting for official verification", "等待官方核验");
      ctx.dom.heroPickNote.textContent = tr("Recommendations appear after refresh", "完成刷新后会自动挑选");
    }
    return;
  }
  ctx.dom.featuredRoot.replaceChildren(...featured.map((resource, index) => featureCard(resource, index === 0, ctx)));
  if (ctx.state.currentView === "recommended") {
    ctx.dom.heroPickTitle.textContent = tr(`${featured.length} resources ready to review`, `${featured.length} 项可以立即查看`);
    ctx.dom.heroPickNote.textContent = tr(`${featured.map((item) => item.provider).join(" · ")} · distinct providers`, `${featured.map((item) => item.provider).join(" · ")}，避免同一供应商重复`);
  }
}

export function renderSummary(ctx, summary, officialResources) {
  ctx.setLocale?.(summary.default_locale);
  const gpuProviders = new Set(officialResources.filter((resource) => resource.kind === "gpu").map((resource) => resource.provider));
  const tierA = officialResources.filter((resource) => resource.priority_tier === "A").length;
  ctx.dom.summaryRoot.replaceChildren(
    metric(tr("Official free resources", "官方免费资源"), String(officialResources.length), tr("Verified", "已核验")),
    metric(tr("Best free picks", "纯免费推荐"), String(tierA), tr("Tier A", "A 级")),
    metric(tr("Free GPU providers", "免费 GPU 来源"), String(gpuProviders.size), tr("Official sources", "官方来源")),
    metric(tr("Pending alerts", "待处理提醒"), String(summary.notifications.unread), summary.notifications.unread ? tr("Review needed", "请查看") : tr("None", "暂无")),
  );
  const sources = summary.sources || {};
  const fresh = sources.fresh ?? sources.healthy ?? 0;
  const issueCount = (sources.overdue || 0) + (sources.stale || 0) + (sources.verification_pending || 0) + (sources.failed || 0) + (sources.never || 0);
  ctx.dom.lastVerified.textContent = sources.oldest_official_verified_at || summary.last_refresh_at
    ? tr(`${formatTime(sources.oldest_official_verified_at || summary.last_refresh_at)} · oldest official verification`, `${formatTime(sources.oldest_official_verified_at || summary.last_refresh_at)} 最旧官方核验`)
    : tr("No official verification yet", "尚未完成官方核验");
  ctx.dom.sourceHealth.querySelector("span:last-child").textContent = tr(`${fresh}/${sources.total || 0} sources fresh`, `${fresh}/${sources.total || 0} 来源新鲜`);
  ctx.dom.sourceHealth.classList.toggle("unhealthy", issueCount > 0);
  ctx.dom.sourceHealthBar.style.width = `${sources.total ? (fresh / sources.total) * 100 : 0}%`;
  ctx.dom.healthySourceCount.textContent = tr(`${fresh} fresh`, `${fresh} 个新鲜`);
  const labels = [["overdue", "overdue", "逾期"], ["stale", "stale", "过期"], ["verification_pending", "pending verification", "待核验"], ["failed", "failed", "失败"], ["never", "never run", "未运行"]]
    .map(([key, en, zh]) => sources[key] ? tr(`${sources[key]} ${en}`, `${sources[key]} 个${zh}`) : "").filter(Boolean);
  ctx.dom.failedSourceCount.textContent = labels.join(" · ") || tr("All healthy", "全部正常");
}

function importantChanges(changes) {
  return changes.filter((change) => ["high", "critical"].includes(change.importance) || (["A", "B"].includes(change.priority_tier) && ["removed", "quota_changed", "limits_changed", "expiring"].includes(change.change_type)));
}

export function renderChangePreview(ctx, changes) {
  const important = importantChanges(changes).slice(0, 2);
  if (!important.length) {
    const row = ctx.element("div", "mini-change");
    const copy = ctx.element("div");
    copy.append(ctx.element("strong", "", "暂无重要变化"), ctx.element("small", "", "社区新线索不会触发系统提醒"));
    row.append(copy, ctx.element("span", "change-tag", "已同步"));
    ctx.dom.changePreview.replaceChildren(row);
    return;
  }
  ctx.dom.changePreview.replaceChildren(...important.map((change) => {
    const row = ctx.element("div", "mini-change");
    const copy = ctx.element("div");
    copy.append(ctx.element("strong", "", `${change.provider || "未知来源"} · ${ctx.changeLabel(change.change_type)}`), ctx.element("small", "", change.title || change.offer_id));
    row.append(copy, ctx.element("span", "change-tag", change.priority_tier || "变化"));
    return row;
  }));
}

export async function loadDashboard(ctx) {
  try {
    const resourceParameters = new URLSearchParams({ verified: "true", limit: "200" });
    if (ctx.dom.noCard.checked) resourceParameters.set("no_card", "true");
    if (ctx.dom.country.value.trim()) resourceParameters.set("country", ctx.dom.country.value.trim());
    if (ctx.dom.region.value.trim()) resourceParameters.set("region", ctx.dom.region.value.trim());
    if (ctx.dom.includeUnknownRegion.checked) resourceParameters.set("include_unknown_region", "true");
    if (ctx.state.locale) resourceParameters.set("locale", ctx.state.locale);
    const [summary, officialPayload, changesPayload] = await Promise.all([
      ctx.fetchJson("/api/ai-resources/summary"),
      ctx.fetchJson(`/api/ai-resources?${resourceParameters}`),
      ctx.fetchJson("/api/ai-resources/changes?days=30&limit=200"),
    ]);
    renderSummary(ctx, summary, officialPayload.resources);
    renderFeatured(ctx, officialPayload.resources);
    renderChangePreview(ctx, changesPayload.changes);
  } catch {
    ctx.dom.summaryRoot.replaceChildren(metric("资源雷达", "暂不可用", "本地数据库尚未准备好"));
    ctx.dom.featuredRoot.replaceChildren(ctx.element("div", "radar-empty", "暂时无法读取推荐资源。"));
    ctx.dom.sourceHealth.classList.add("unhealthy");
    ctx.dom.sourceHealth.querySelector("span:last-child").textContent = "来源状态不可用";
  }
}
