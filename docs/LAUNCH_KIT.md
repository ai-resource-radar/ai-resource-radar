# v0.4 launch kit (draft only)

This file prepares copy for a human to review. It does **not** post to any service, create an
account, or trigger a release. Replace `{LIVE_URL}`, `{DATA_URL}`, and `{REPO_URL}` with the final
links only after the Pages workflow has produced a healthy or partial manifest. Do not invent
counts, savings, uptime, or provider endorsements; if a number is useful, quote the dated public
manifest.

## English copy

### Short (one sentence)

AI Resource Radar checks public free-token, GPU, and price changes every day, then shows what you
get and how to claim it: {LIVE_URL}.

### Medium (social post)

Free tiers and GPU prices move faster than a bookmark list. AI Resource Radar v0.4 runs deterministic
public-source checks, keeps the last trusted value when a parser drifts, and publishes a small JSON
snapshot plus a human-friendly radar. Browse {LIVE_URL}, inspect {DATA_URL}, or run it locally with
`uvx ai-resource-radar start --open`. MIT licensed, local-first, and no account data is
needed for collection.

### Long (project introduction)

AI Resource Radar is a local-first tracker for free AI tokens, GPU compute, grants, and normalized
prices. Its source-specific parsers retain evidence and verification time, distinguish official
facts from community leads, and report changes instead of hiding them in a score. v0.4 adds eight
official sources, transactional tip batches, and a strictly gated free CogView poster benchmark.
The public Pages view and documented JSON schema remain keyless: a single
source can become `partial` without erasing trusted data, while a severe or invalid build is
stopped before it can replace the previous site. Start at {LIVE_URL}, download the data at
{DATA_URL}, or try `uvx ai-resource-radar start --open`. Read the security and
migration notes before integrating the data into another tool.

## 中文文案

### 短文案（一句话）

AI 免费资源雷达每天核验公开的免费 Token、GPU 算力和价格变化，直接告诉你送什么、怎么领：{LIVE_URL}。

### 中文中等文案（社交平台）

免费额度和 GPU 价格变化很快，收藏夹很容易过期。AI 免费资源雷达 v0.4 用确定性脚本核验公开来源，
解析器漂移时保留最后可信值，并发布可核对的 JSON 快照和可读榜单。访问 {LIVE_URL}、查看 {DATA_URL}，
或用 `uvx ai-resource-radar start --open` 本地运行。采集不需要账号信息，项目采用 MIT 许可证。

### 中文长文案（项目介绍）

AI 免费资源雷达是本地优先的免费 Token、GPU 算力、资助和价格追踪器。每个来源都有专用解析器、官方
证据和核验时间；社区目录只用于发现线索，不会把未经核验的内容标成官方。v0.4 增加 8 个官方来源、
技巧整批事务纳管和免费智谱海报的严格本机基准。GitHub Pages 与稳定 JSON 数据继续保持：单个来源失败
会标为 `partial`，不会清空其他来源；严重的数据完整性
问题会在发布前停止，旧站保持不变。你可以从 {LIVE_URL} 开始，下载 {DATA_URL}，或运行
`uvx ai-resource-radar start --open`。接入前请阅读隐私、安全和迁移说明。

## First launch channel

This is a review prompt, not an automatic publishing instruction. The first v0.4 launch is limited
to 掘金. V2EX and every other external channel are intentionally skipped.

| Channel | Suggested angle and constraints |
| --- | --- |
| 掘金 | Publish a technical walkthrough: source allow-list → parser → normalized SQLite → public manifest and partial gate. Include the `uvx` command and a small, dated example; label every screenshot as sample data. |

## Before any post

- [ ] Confirm `{LIVE_URL}` loads and `{DATA_URL}` has a dated `healthy` or `partial` manifest.
- [ ] Replace placeholders with links; do not add fabricated counts or provider endorsements.
- [ ] Re-read the target community's current rules and disclose affiliation where required.
- [ ] Remove local paths, logs, cookies, API keys, and account-specific screenshots.
- [ ] Have a maintainer review claims and links. This kit intentionally stops before publishing.
