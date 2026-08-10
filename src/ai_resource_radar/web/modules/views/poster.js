/* Daily poster tool view. */
import { compactNumber, formatTime } from "/ai-radar-assets/modules/formatters.js";
import { element } from "/ai-radar-assets/modules/components.js";

export const viewId = "poster";
export const section = "工具";

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
    chinese_ocr_benchmark_required: "需要完成 6 组中文 OCR 基准",
    chinese_ocr_benchmark_failed: "中文 OCR 基准未通过",
    benchmark_two_days_required: "6 组样例必须跨至少两个自然日完成",
    benchmark_manual_review_required: "等待人工确认版式无重影、裁切和错位",
    poster_benchmark_model_not_selected: "先选择 CogView 基准模型（可保持日报关闭）",
    openai_keychain_credential_missing: "Keychain 中没有 OpenAI 凭据",
    openclaw_unavailable: "未找到 OpenClaw",
    openclaw_provider_status_unavailable: "无法读取 OpenClaw 图片供应商状态",
    openclaw_provider_zai_not_configured: "OpenClaw 尚未配置 ZAI",
    "openclaw_model_cogview-3-flash_not_configured": "OpenClaw 未启用 CogView-3-Flash",
    poster_model_unsupported: "当前运行版本不支持所选模型",
  }[reason] || reason || "无";
}

async function startPosterBenchmark(ctx) {
  ctx.dom.refreshState.hidden = false;
  ctx.dom.refreshState.textContent = "正在生成免费基准海报并校验最终 WebP…";
  try {
    await ctx.fetchJson("/api/ai-daily/benchmark", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ cases: 3 }) });
    pollPosterBenchmark(ctx);
  } catch (error) {
    ctx.dom.refreshState.textContent = error.message === "poster_benchmark_already_running" ? "海报基准任务已经在运行。" : "无法启动海报基准。";
  }
}

async function pollPosterBenchmark(ctx) {
  try {
    const status = await ctx.fetchJson("/api/ai-daily/status");
    if (status.benchmark_task?.status === "running") {
      ctx.dom.refreshState.hidden = false;
      ctx.dom.refreshState.textContent = "CogView 正在生成，完成后会检查 MIME、3:4 比例、OCR 和数字白名单…";
      window.setTimeout(() => pollPosterBenchmark(ctx), 1500);
      return;
    }
    ctx.dom.refreshState.hidden = false;
    ctx.dom.refreshState.textContent = status.benchmark_task?.status === "completed" ? "本轮基准完成。" : `基准未通过：${posterReasonLabel(status.benchmark_task?.error)}`;
    loadPoster(ctx);
  } catch {
    ctx.dom.refreshState.hidden = false;
    ctx.dom.refreshState.textContent = "无法读取海报基准状态。";
  }
}

async function approvePosterBenchmark(ctx) {
  if (!window.confirm("我已逐张确认 6 张最终 WebP 无明显重影、裁切或错位，允许该模型用于正式日报。")) return;
  ctx.dom.refreshState.hidden = false;
  ctx.dom.refreshState.textContent = "正在记录人工审核…";
  try {
    await ctx.fetchJson("/api/ai-daily/benchmark/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approve: true, notes: "Dashboard 人工确认无明显重影、裁切或错位。" }) });
    ctx.dom.refreshState.textContent = "人工审核已通过；现在可以启用免费日报模型。";
    loadPoster(ctx);
  } catch (error) {
    ctx.dom.refreshState.textContent = `无法批准基准：${posterReasonLabel(error.message)}`;
  }
}

function posterBenchmarkPanel(status, ctx) {
  const benchmark = status.benchmark;
  if (!benchmark) return null;
  const panel = element("section", "poster-benchmark");
  const heading = element("div", "poster-benchmark-heading");
  const copy = element("div");
  copy.append(element("span", "poster-kicker", `LOCAL BENCHMARK · ${benchmark.benchmark_version}`), element("h3", "", `中文准确性 ${benchmark.passed_cases} / ${benchmark.required_cases}`), element("p", "", posterReasonLabel(benchmark.reason)));
  const actions = element("div", "poster-benchmark-actions");
  const run = element("button", "poster-generate", "运行下一批");
  run.type = "button";
  run.disabled = !benchmark.configured || benchmark.remaining_calls_today <= 0 || benchmark.passed_cases >= benchmark.required_cases || status.benchmark_task?.status === "running";
  run.title = !benchmark.configured ? posterReasonLabel(benchmark.configuration_reason) : `今天剩余 ${benchmark.remaining_calls_today} 次免费调用`;
  run.addEventListener("click", () => startPosterBenchmark(ctx));
  const approve = element("button", "poster-download", "人工确认通过");
  approve.type = "button";
  approve.disabled = !benchmark.ocr_passed || !benchmark.two_days_passed || benchmark.manual_review_status === "approved";
  approve.addEventListener("click", () => approvePosterBenchmark(ctx));
  actions.append(run, approve);
  heading.append(copy, actions);
  const cases = element("div", "poster-benchmark-cases");
  benchmark.cases.forEach((item) => cases.append(element("span", item.status === "success" ? "poster-ok" : "poster-warn", `${item.case_id} · ${item.status === "success" ? "OCR 通过" : item.status === "failed" ? "未通过" : "待运行"}`)));
  panel.append(heading, element("p", "poster-benchmark-budget", `今日图片调用：${benchmark.attempts_today} / 3；基准与日报共用硬上限。`), cases);
  return panel;
}

function posterMeta(publishedReport, status, todayReport) {
  const meta = element("div", "poster-meta");
  const modelProvider = publishedReport?.provider || status.provider;
  const modelName = publishedReport?.model || status.model;
  meta.append(
    element("span", todayReport?.status === "success" ? "poster-ok" : "poster-warn", posterStatusLabel(todayReport)),
    element("span", "", `${modelProvider} / ${modelName}`),
    element("span", status.enabled ? "poster-ok" : "poster-warn", status.enabled ? "日报已启用" : "日报已关闭"),
    element("span", status.formal_poster_eligible ? "poster-ok" : "poster-warn", status.formal_poster_eligible ? "正式日报可用" : posterReasonLabel(status.reason)),
    element("span", "", `调用 ${todayReport?.attempt_count || 0} / 3`),
    element("span", "", publishedReport?.generated_at ? formatTime(publishedReport.generated_at) : "等待生成"),
  );
  if (status.last_failure?.error_code) meta.append(element("span", "poster-warn", `最近失败：${posterStatusLabel({ status: "failed", error_code: status.last_failure.error_code })}`));
  return meta;
}

function posterHistoryCard(report) {
  const card = element("article", "poster-history-card");
  const heading = element("div");
  heading.append(element("strong", "", report.report_date), element("small", "", posterStatusLabel(report)));
  card.append(heading);
  if (report.image_url) {
    const link = element("a", "poster-history-link");
    link.href = report.image_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.append(element("span", "", "查看海报"));
    card.append(link);
  } else card.append(element("span", "poster-history-error", report.error_code || "未生成图片"));
  return card;
}

async function pollPoster(ctx) {
  try {
    const status = await ctx.fetchJson("/api/ai-daily/status");
    if (status.task?.status === "running") {
      ctx.dom.refreshState.hidden = false;
      ctx.dom.refreshState.textContent = "图片模型正在生成并进行本地 OCR 校验…";
      window.setTimeout(() => pollPoster(ctx), 1500);
      return;
    }
    ctx.dom.refreshState.hidden = false;
    ctx.dom.refreshState.textContent = status.task?.status === "completed" ? "日报海报已通过校验并发布。" : `日报未发布：${posterStatusLabel(status.task?.report || { status: "failed", error_code: status.task?.error })}`;
    loadPoster(ctx);
  } catch {
    ctx.dom.refreshState.hidden = false;
    ctx.dom.refreshState.textContent = "无法读取日报生成状态。";
  }
}

async function startPoster(force, ctx) {
  ctx.dom.refreshState.hidden = false;
  ctx.dom.refreshState.textContent = "正在启动纯图片日报生成…";
  try {
    await ctx.fetchJson("/api/ai-daily/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ force }) });
    pollPoster(ctx);
  } catch (error) {
    ctx.dom.refreshState.textContent = error.message === "daily_poster_already_running" ? "日报生成任务已经在运行。" : "无法启动日报生成任务。";
  }
}

export async function loadPoster(ctx) {
  ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "正在读取日报海报…"));
  try {
    const [latestPayload, historyPayload, status] = await Promise.all([
      ctx.fetchViewJson("/api/ai-daily/latest"),
      ctx.fetchViewJson("/api/ai-daily?days=90"),
      ctx.fetchViewJson("/api/ai-daily/status"),
    ]);
    const latest = latestPayload.report;
    ctx.dom.catalogCaption.textContent = "只展示通过本机 OCR 文字和数字校验的最终图片";
    const layout = element("div", "poster-layout");
    const stage = element("section", "poster-stage");
    const stageHeading = element("div", "poster-stage-heading");
    const copy = element("div");
    copy.append(element("span", "poster-kicker", "LATEST VERIFIED POSTER"), element("h3", "", latest ? `${latest.report_date} 日报` : "等待第一张合格日报"));
    const generate = element("button", "poster-generate", status.today?.status === "success" ? "重新生成" : "生成今日海报");
    generate.type = "button";
    generate.disabled = !status.enabled || !status.configured || !status.formal_poster_eligible || status.task?.status === "running" || (status.today?.attempt_count || 0) >= status.max_attempts_per_day;
    generate.title = !status.enabled ? "请先启用日报" : !status.configured ? posterReasonLabel(status.configuration_reason) : !status.formal_poster_eligible ? posterReasonLabel(status.reason) : "生成一张经过最终 WebP OCR 校验的日报";
    generate.addEventListener("click", () => startPoster(status.today?.status === "success", ctx));
    stageHeading.append(copy, generate);
    stage.append(stageHeading, posterMeta(latest, status, status.today));
    const benchmarkPanel = posterBenchmarkPanel(status, ctx);
    const diagnostics = element("details", "poster-diagnostics");
    const summary = element("summary", "", "展开日报诊断");
    diagnostics.append(summary, benchmarkPanel || element("p", "poster-diagnostics-empty", "当前没有可展开的基准记录。"));
    diagnostics.addEventListener("toggle", () => {
      summary.textContent = diagnostics.open ? "收起日报诊断" : "展开日报诊断";
    });
    stage.append(diagnostics);
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
      actions.append(download, element("span", "", `${latest.image_bytes ? compactNumber(latest.image_bytes / 1024) : "—"} KB · 1080 × 1440`));
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
        emptyHelp = status.provider === "openai" ? "运行：ai-radar poster key set" : `请先在 OpenClaw 配置图片供应商：${posterReasonLabel(status.configuration_reason)}`;
      } else if (!status.formal_poster_eligible) {
        emptyTitle = "当前模型只能用于生图测试";
        emptyHelp = `正式日报已在调用 API 前拦截：${posterReasonLabel(status.reason)}`;
      }
      empty.append(element("strong", "", emptyTitle), element("p", "", emptyHelp));
      stage.append(empty);
    }
    const history = element("aside", "poster-history");
    history.append(element("span", "poster-kicker", "90 DAY HISTORY"), element("h3", "", "生成记录"), element("p", "", "失败候选图片会立即删除，只保留状态与错误代码。"));
    const historyList = element("div", "poster-history-list");
    if (historyPayload.reports.length) historyList.append(...historyPayload.reports.map(posterHistoryCard));
    else historyList.append(element("div", "mini-empty", "暂无日报记录"));
    history.append(historyList);
    layout.append(stage, history);
    ctx.dom.resultsRoot.replaceChildren(layout);
  } catch (error) {
    if (ctx.isAbortError(error)) return;
    ctx.dom.resultsRoot.replaceChildren(element("div", "radar-empty", "暂时无法读取日报海报。"));
  }
}
