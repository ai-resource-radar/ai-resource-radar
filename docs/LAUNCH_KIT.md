# Growth launch kit (draft only)

This draft does **not** post to any service, modify GitHub metadata, create an account, or trigger a
release. Every external post, directory submission, organization-profile edit, and publication
still requires a fresh approval for the exact destination and final copy. Never invent counts,
savings, uptime, or provider endorsements; if a number is useful, quote the dated public manifest.

## Positioning

Lead with one decision: find a free AI API or GPU option that works in the reader's country, with
no-card options first and official evidence attached. Price rankings, the local Dashboard, feeds,
and optional extensions support that decision but should not compete with it in the opening copy.

## English copy

### Short (one sentence)

AI Resource Radar checks public free-token, GPU, and price changes every day, then shows what you
get and how to claim it: {LIVE_URL}.

### Medium (social post)

Free tiers and GPU prices move faster than a bookmark list. AI Resource Radar v0.9.0 runs deterministic
public-source checks, keeps the last trusted value when a parser drifts, and publishes a small JSON
snapshot plus a human-friendly radar. Browse {LIVE_URL}, inspect {DATA_URL}, or run it locally with
`uvx ai-resource-radar start --open`. MIT licensed, local-first, and no account data is
needed for collection.

### Long (project introduction)

AI Resource Radar is a local-first tracker for free AI tokens, GPU compute, grants, and normalized
prices. Its source-specific parsers retain evidence and verification time, distinguish official
facts from community leads, and report changes instead of hiding them in a score. v0.9.0 keeps the
collection and public snapshot focused on free resources and prices while adding country-level
availability and explicit signup requirements.
The public Pages view and documented JSON schema remain keyless: a single
source can become `partial` without erasing trusted data, while a severe or invalid build is
stopped before it can replace the previous site. Start at {LIVE_URL}, download the data at
{DATA_URL}, or try `uvx ai-resource-radar start --open`. Read the security and
migration notes before integrating the data into another tool.

## 中文文案

### 短文案（一句话）

AI 免费资源雷达每天核验公开的免费 Token、GPU 算力和价格变化，直接告诉你送什么、怎么领：{LIVE_URL}。

### 中文中等文案（社交平台）

免费额度和 GPU 价格变化很快，收藏夹很容易过期。AI 免费资源雷达 v0.9.0 用确定性脚本核验公开来源，
解析器漂移时保留最后可信值，并发布可核对的 JSON 快照和可读榜单。访问 {LIVE_URL}、查看 {DATA_URL}，
或用 `uvx ai-resource-radar start --open` 本地运行。采集不需要账号信息，项目采用 MIT 许可证。

### 中文长文案（项目介绍）

AI 免费资源雷达是本地优先的免费 Token、GPU 算力、资助和价格追踪器。每个来源都有专用解析器、官方
证据和核验时间；社区目录只用于发现线索，不会把未经核验的内容标成官方。GitHub Pages 与稳定 JSON
数据继续保持聚焦免费资源和价格：单个来源失败
会标为 `partial`，不会清空其他来源；严重的数据完整性
问题会在发布前停止，旧站保持不变。你可以从 {LIVE_URL} 开始，下载 {DATA_URL}，或运行
`uvx ai-resource-radar start --open`。接入前请阅读隐私、安全和迁移说明。

## GitHub-native shortlist (reviewed 2026-09-12)

External GitHub directory submissions are not approved by this document. Re-read the destination's
rules and recheck the live radar immediately before opening any pull request.

| Priority | Candidate | Decision and constraint |
| --- | --- | --- |
| 1 | `eudk/awesome-ai-tools` | Best current external fit under **LLM Ops**. It accepts public, usable developer tools, requires concise factual copy and asks contributors to disclose their connection. Its pull-request queue is large, so treat this as a durable backlink rather than an immediate traffic spike. |
| 2 | GitHub organization profile | Publish the one-sentence profile below as a second first-party GitHub entry point. This is useful brand hygiene, not third-party endorsement. |
| Later | `marcelscruz/dev-resources` | Strong developer audience, but its rules reject products hosted on shared `github.io` domains. Revisit only after the project has a custom domain. |
| Later | `awesome-selfhosted/awesome-selfhosted-data` | Revisit after the first tagged release is at least four months old and the project clearly fits an existing self-hosted category. |
| Skip | `mnfst/awesome-free-llm-apis` | Accepts API providers with permanent free LLM tiers, not comparison or monitoring tools. |
| Skip | `public-apis` | The hosted snapshot is not a documented, self-serve product API and the current `github.io` host violates its custom-domain rule. |
| Skip | `github/explore` | Curates topic and collection definitions rather than accepting individual project listings. The repository already has focused GitHub topics. |

### Prepared `eudk/awesome-ai-tools` submission

Target section: `LLM Ops`

Entry:

> [AI Resource Radar](https://github.com/ai-resource-radar/ai-resource-radar) - Open-source,
> local-first tracker for daily-verified free AI APIs, GPU compute, grants, and normalized token/GPU
> prices, with country and no-card filters plus official evidence.

Pull request title:

> Add AI Resource Radar to LLM Ops

Pull request body:

> Adds AI Resource Radar to the LLM Ops section. The project is public and usable now through its
> hosted read-only radar or locally with `uvx`; it is MIT licensed and verifies provider claims
> against official sources. Disclosure: I maintain this project. This submission was prepared with
> an AI coding assistant.

Submission gate: first deploy the SiliconFlow source repair, confirm a fresh publishable manifest,
then recheck that the entry is still absent and that the contribution rules have not changed.

## Organization profile draft

> Daily-verified free AI APIs, GPU compute, and prices—filtered by country, signup requirements,
> and official evidence. Browse the public radar without an account or API key.

Homepage: `https://ai-resource-radar.github.io/ai-resource-radar/`

## Before any post

- [ ] Confirm `{LIVE_URL}` loads and `{DATA_URL}` has a dated `healthy` or `partial` manifest.
- [ ] Confirm the Search Console experiment result instead of inferring indexing from a public search sample.
- [ ] Replace placeholders with links; do not add fabricated counts or provider endorsements.
- [ ] Re-read the target community's current rules and disclose affiliation where required.
- [ ] Remove local paths, logs, cookies, API keys, and account-specific screenshots.
- [ ] Have a maintainer review claims and links. This kit intentionally stops before publishing.
