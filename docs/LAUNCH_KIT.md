# v0.3 launch kit (draft only)

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

Free tiers and GPU prices move faster than a bookmark list. AI Resource Radar v0.3 runs deterministic
public-source checks, keeps the last trusted value when a parser drifts, and publishes a small JSON
snapshot plus a human-friendly radar. Browse {LIVE_URL}, inspect {DATA_URL}, or run it locally with
`uvx ai-resource-radar start --open`. MIT licensed, local-first, and no account data is
needed for collection.

### Long (project introduction)

AI Resource Radar is a local-first tracker for free AI tokens, GPU compute, grants, and normalized
prices. Its source-specific parsers retain evidence and verification time, distinguish official
facts from community leads, and report changes instead of hiding them in a score. v0.3 adds a
static Pages view and a documented public JSON schema. The daily workflow is keyless: a single
source can become `partial` without erasing trusted data, while a severe or invalid build is
stopped before it can replace the previous site. Start at {LIVE_URL}, download the data at
{DATA_URL}, or try `uvx ai-resource-radar start --open`. Read the security and
migration notes before integrating the data into another tool.

## 中文文案

### 短文案（一句话）

AI 免费资源雷达每天核验公开的免费 Token、GPU 算力和价格变化，直接告诉你送什么、怎么领：{LIVE_URL}。

### 中文中等文案（社交平台）

免费额度和 GPU 价格变化很快，收藏夹很容易过期。AI 免费资源雷达 v0.3 用确定性脚本核验公开来源，
解析器漂移时保留最后可信值，并发布可核对的 JSON 快照和可读榜单。访问 {LIVE_URL}、查看 {DATA_URL}，
或用 `uvx ai-resource-radar start --open` 本地运行。采集不需要账号信息，项目采用 MIT 许可证。

### 中文长文案（项目介绍）

AI 免费资源雷达是本地优先的免费 Token、GPU 算力、资助和价格追踪器。每个来源都有专用解析器、官方
证据和核验时间；社区目录只用于发现线索，不会把未经核验的内容标成官方。v0.3 增加了 GitHub Pages
公开站点和稳定的 JSON 数据说明：单个来源失败会标为 `partial`，不会清空其他来源；严重的数据完整性
问题会在发布前停止，旧站保持不变。你可以从 {LIVE_URL} 开始，下载 {DATA_URL}，或运行
`uvx ai-resource-radar start --open`。接入前请阅读隐私、安全和迁移说明。

## Channel notes

These are review prompts, not automatic publishing instructions. Keep the factual core above and
adapt the first sentence to each community's format.

| Channel | Suggested angle and constraints |
| --- | --- |
| Show HN | Lead with the deterministic parser/last-trusted-value design and ask for parser-drift feedback. Include the live link, repository, one command, and a short note that the site is an aggregate view—not an offer guarantee. Avoid marketing adjectives. |
| Product Hunt | Use the short copy as the tagline, the medium copy as the maker comment, and link the public schema. Describe the audience (developers comparing free quotas) and one concrete workflow; do not claim rankings are complete. |
| Reddit | Pick a relevant community and read its self-promotion rules first. Prefer a question (“How do you track changing free tiers?”), include source/region caveats, and disclose that the post is a project announcement. No referral links or scraping claims. |
| V2EX | Use the Chinese short or medium copy, state that collection is keyless and local-first, and link the JSON schema for technical readers. Invite one official source request rather than asking for stars. |
| 掘金 | Publish a technical walkthrough: source allow-list → parser → normalized SQLite → public manifest and partial gate. Include the `uvx` command and a small, dated example; label every screenshot as sample data. |
| 少数派 | Focus on the daily decision (“送什么、怎么领”) and the local dashboard workflow. Explain privacy, the no-account default, and why official links still need checking. Keep the product description practical and avoid urgency language. |

## Before any post

- [ ] Confirm `{LIVE_URL}` loads and `{DATA_URL}` has a dated `healthy` or `partial` manifest.
- [ ] Replace placeholders with links; do not add fabricated counts or provider endorsements.
- [ ] Re-read the target community's current rules and disclose affiliation where required.
- [ ] Remove local paths, logs, cookies, API keys, and account-specific screenshots.
- [ ] Have a maintainer review claims and links. This kit intentionally stops before publishing.
