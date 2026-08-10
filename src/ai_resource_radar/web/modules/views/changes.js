/* Change tracking view. */
import { formatTime } from "/ai-radar-assets/modules/formatters.js";
import { element } from "/ai-radar-assets/modules/components.js";

export const viewId = "changes";
export const section = "跟踪";

export async function loadChanges(ctx) {
  ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在读取变化记录…"));
  try {
    const payload = await ctx.fetchViewJson("/api/ai-resources/changes?days=30&limit=200");
    if (!payload.changes.length) {
      ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "最近 30 天还没有变化记录。"));
      return;
    }
    const rows = payload.changes.map((change) => {
      const row = element("article", "change-row");
      row.append(element("time", "", formatTime(change.detected_at)), element("span", "", ctx.changeLabel(change.change_type)), element("strong", "", `${change.provider || "未知来源"} · ${change.title || change.offer_id}`));
      return row;
    });
    ctx.dom.catalogCaption.textContent = `最近 30 天的 ${payload.changes.length} 条记录`;
    ctx.dom.resultsRoot.replaceChildren(...rows);
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取变化记录。"));
  }
}
