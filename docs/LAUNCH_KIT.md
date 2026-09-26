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

### Existing `eudk/awesome-ai-tools` submission

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

Current status, checked 2026-09-26: pull request
[`#625`](https://github.com/eudk/awesome-ai-tools/pull/625) is open and cleanly mergeable, with no
maintainer comments or reviews. Do not bump or duplicate it. Re-read any future maintainer feedback
and the contribution rules before changing the submitted entry.

## Organization profile draft

> Daily-verified free AI APIs, GPU compute, and prices—filtered by country, signup requirements,
> and official evidence. Browse the public radar without an account or API key.

Homepage: `https://ai-resource-radar.github.io/ai-resource-radar/`

## First community launch wave (reviewed 2026-09-26)

Do not publish this wave until the SambaNova repair is merged and the live manifest reports the
merged default-branch revision, `healthy`, `publishable: true`, and 23 fresh sources. The existing
`eudk/awesome-ai-tools` pull request remains the slow, durable directory channel; do not bump it
while it has no maintainer feedback.

### 1. X from the independent project account

Use `docs/assets/readme-public-overview.png` as the first image and
`docs/assets/readme-provider-openrouter.png` as the second. Keep the institutional account separate:
no repost, like, reply, or coordinated engagement.

Draft:

> Free AI tiers change fast, so I built AI Resource Radar: 23 daily source checks for free AI APIs,
> GPU compute, grants, and prices—with country/no-card filters and evidence links. No signup.
>
> Live: https://ai-resource-radar.github.io/ai-resource-radar/
> GitHub: https://github.com/ai-resource-radar/ai-resource-radar

### 2. V2EX / 分享创造

Use this as the first Chinese discussion channel because the project is immediately usable, the
node explicitly welcomes newly created work, and a concrete feedback question fits better than a
pure announcement.

Title:

> 做了一个每天核验 23 个公开来源的 AI 免费资源雷达，想听听大家最在意哪类资源

Body:

> 免费 API、GPU 额度和价格经常变化，普通收藏夹很快就过期，所以我做了 AI Resource
> Radar：每天读取公开来源，保留证据和核验时间，并按国家、是否需要绑卡等条件筛选。
>
> 在线版：https://ai-resource-radar.github.io/ai-resource-radar/zh/
>
> GitHub：https://github.com/ai-resource-radar/ai-resource-radar
>
> 目前最想确认两件事：你找免费 AI 资源时最先看「额度、地区、是否绑卡」中的哪一项？还有哪些
> 官方来源值得加入？欢迎直接提数据错误，项目里也有修正入口。

### 3. Show HN after account warm-up

Show HN currently limits submissions from accounts that are not yet familiar with the community.
Treat it as the third channel, not an immediate launch. When eligible, submit the working public
radar rather than a blog post, stay available for questions, and never solicit votes.

Title:

> Show HN: AI Resource Radar – daily checks for free AI APIs and GPU prices

First comment:

> I built this after repeatedly finding that saved free-tier pages had become outdated. The radar
> checks allow-listed public sources, keeps the last trusted observation when one parser fails, and
> publishes the source evidence and verification time. The hosted view needs no account; the same
> data can also run locally. I would especially value feedback on missing official sources and on
> whether the country/no-card filters answer the first decision you make.

Rules to recheck immediately before publishing:

- Show HN: https://news.ycombinator.com/showhn.html
- V2EX 分享创造: https://www.v2ex.com/go/create
- X link and image behavior: https://help.x.com/en/using-x/how-to-post

## Before any post

- [ ] Confirm `{LIVE_URL}` loads and `{DATA_URL}` has a dated `healthy` or `partial` manifest.
- [ ] Confirm the Search Console experiment result instead of inferring indexing from a public search sample.
- [ ] Replace placeholders with links; do not add fabricated counts or provider endorsements.
- [ ] Re-read the target community's current rules and disclose affiliation where required.
- [ ] Remove local paths, logs, cookies, API keys, and account-specific screenshots.
- [ ] Have a maintainer review claims and links. This kit intentionally stops before publishing.
