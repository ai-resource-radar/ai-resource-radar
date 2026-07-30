# AI 免费资源雷达

[English](README.md)

AI 免费资源雷达是一个本地优先、证据驱动的 AI 资源追踪器，重点关注：

- 免费 Token 和 API 额度；
- 免费 GPU 算力与资助活动；
- Token、GPU 标准化费用榜单；
- 新增、额度变化、限制变化、下架和到期提醒；
- 可选的 GPT Image 2 纯图片日报。

默认采集链路完全由确定性脚本执行，不调用 AI，不需要 API Key、Cookie 或账号信息。只有日报海报会使用图片模型；发布前会通过 macOS Vision 在本机核对文字和数字。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

ai-radar refresh
ai-radar dashboard --open
```

独立 Dashboard 只绑定 `127.0.0.1:18766`。

## 纯图片日报

日报固定精选 5 项：3 个官方核验的免费资源、1 个 Token 价格和 1 个 GPU 小时价。海报由图片模型整张生成，程序不会叠加或重写正文。

```bash
ai-radar poster key set
ai-radar poster generate
ai-radar poster latest
```

API Key 通过隐藏输入写入 macOS 钥匙串，不会进入 SQLite、配置文件、日志或 Git。每天最多调用图片模型 3 次；文字、服务商、额度或价格校验仍不通过时，当日停发并继续展示上一张有效海报。

安装 Dashboard、菜单栏和每天 08:00 的任务：

```bash
ai-radar service install
ai-radar service status
```

## 数据与隐私

- 官方来源默认 24 小时核验；社区目录按来源周期发现线索。
- 只请求白名单 HTTPS，支持 ETag/Last-Modified、16 MB 上限、超时和来源故障隔离。
- SQLite schema v4，权限 `0600`；抓取日志保留 90 天，普通变化保留 365 天。
- 海报保留 90 天，失败候选图片立即删除。
- Dashboard 仅接受本机 Host/Origin，并且所有静态资源均在本地。

更多信息见[架构说明](docs/ARCHITECTURE.md)、[安全说明](docs/SECURITY.md)和[贡献指南](CONTRIBUTING.md)。

## 开发

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
node --check src/ai_resource_radar/web/ai-resources.js
```

## License

MIT
