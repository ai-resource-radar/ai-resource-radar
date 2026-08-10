from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
from typing import Any

from ai_resource_radar.dashboard import serve
from ai_resource_radar.doctor import diagnose
from ai_resource_radar.paths import default_database_path
from ai_resource_radar.public_site import PublicSiteError, build_public_site
from ai_resource_radar.poster import (
    KeychainStore,
    configure_poster,
    daily_report_status,
    generate_daily_poster,
    latest_daily_report,
    list_daily_reports,
    list_poster_models,
    poster_benchmark_status,
    review_poster_benchmark,
    run_poster_benchmark,
    test_poster_model,
)
from ai_resource_radar.locks import OperationLockedError
from ai_resource_radar.runtime import refresh
from ai_resource_radar.service import install, status, uninstall
from ai_resource_radar.sources import SOURCE_BY_ID
from ai_resource_radar.store import (
    UnsupportedSchemaError,
    list_changes,
    list_offers,
    radar_summary,
)
from ai_resource_radar.tips import (
    TIP_CATEGORIES,
    add_tip,
    approve_tip_batch,
    get_tip,
    list_tip_applications,
    list_tip_application_batches,
    list_tips,
    refresh_official_tips,
    review_tip,
    rollback_tip_batch,
    rollback_tip_application,
    seed_initial_tips,
)
from ai_resource_radar.interfaces.cli import CliContext

def _parser(context: CliContext | None = None) -> argparse.ArgumentParser:
    context = context or CliContext()
    database = context.database or default_database_path()
    parser = argparse.ArgumentParser(
        prog="ai-radar",
        description="确定性采集 AI 免费资源与价格，并可生成纯图片日报。",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    refresh_parser = actions.add_parser("refresh", help="刷新本地资源库")
    refresh_parser.add_argument("--database", type=Path, default=database)
    refresh_parser.add_argument("--source", action="append", choices=tuple(SOURCE_BY_ID))
    refresh_parser.add_argument("--timeout", type=float, default=20)
    refresh_parser.add_argument("--force", action="store_true")
    refresh_parser.add_argument("--official-only", action="store_true")
    refresh_parser.add_argument("--output", type=Path)

    list_parser = actions.add_parser("list", help="查看当前资源")
    list_parser.add_argument("--database", type=Path, default=database)
    list_parser.add_argument("--kind", choices=("token", "gpu", "grant"))
    list_parser.add_argument("--verified-only", action="store_true")
    list_parser.add_argument("--no-card", action="store_true")
    list_parser.add_argument("--free-image-generation", action="store_true")
    list_parser.add_argument("--mainland", choices=("supported", "unknown", "unsupported"))
    list_parser.add_argument("--query")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.add_argument("--only-free", action="store_true")
    list_parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default=context.list_format,
    )
    list_parser.add_argument("--output", type=Path)

    changes_parser = actions.add_parser("changes", help="查看变化历史")
    changes_parser.add_argument("--database", type=Path, default=database)
    changes_parser.add_argument("--days", type=int, default=30)
    changes_parser.add_argument("--limit", type=int, default=100)
    changes_parser.add_argument("--output", type=Path)

    tips = actions.add_parser("tips", help="发现、审核并应用 AI 效率技巧")
    tip_actions = tips.add_subparsers(dest="tips_action", required=True)
    tip_list = tip_actions.add_parser("list", help="查看技巧")
    tip_list.add_argument("--database", type=Path, default=database)
    tip_list.add_argument("--status", choices=("candidate", "approved", "rejected", "retired"))
    tip_list.add_argument("--category", choices=tuple(sorted(TIP_CATEGORIES)))
    tip_list.add_argument("--query")
    tip_list.add_argument("--limit", type=int, default=100)
    tip_list.add_argument("--offset", type=int, default=0)
    tip_show = tip_actions.add_parser("show", help="查看技巧详情")
    tip_show.add_argument("tip_id")
    tip_show.add_argument("--database", type=Path, default=database)
    for action_name in ("import", "add"):
        tip_add = tip_actions.add_parser(action_name, help="手动导入结构化技巧")
        tip_add.add_argument("--database", type=Path, default=database)
        tip_add.add_argument(
            "--url" if action_name == "import" else "--source-url",
            required=action_name == "import",
        )
        tip_add.add_argument("--title", required=True)
        tip_add.add_argument("--category", required=True, choices=tuple(sorted(TIP_CATEGORIES)))
        tip_add.add_argument("--summary", required=True)
        tip_add.add_argument("--instruction", required=True)
        tip_add.add_argument("--example", default="")
        tip_add.add_argument("--constraint", action="append", default=[])
        tip_add.add_argument("--tag", action="append", default=[])
        tip_add.add_argument("--risk", choices=("low", "medium", "high"), default="medium")
    tip_approve = tip_actions.add_parser("approve", help="批准并自动应用技巧")
    tip_approve.add_argument("tip_id")
    tip_approve.add_argument("--database", type=Path, default=database)
    tip_approve.add_argument("--scope", required=True, choices=("global", "project", "both"))
    tip_approve_batch = tip_actions.add_parser("approve-batch", help="事务性批准并应用一组技巧")
    tip_approve_batch.add_argument("tip_ids", nargs="+")
    tip_approve_batch.add_argument("--database", type=Path, default=database)
    tip_approve_batch.add_argument("--scope", required=True, choices=("global", "project", "both"))
    tip_approve_batch.add_argument("--adopt-existing", action="store_true")
    tip_reject = tip_actions.add_parser("reject", help="拒绝候选技巧")
    tip_reject.add_argument("tip_id")
    tip_reject.add_argument("--database", type=Path, default=database)
    tip_reject.add_argument("--reason", default="")
    tip_apps = tip_actions.add_parser("applications", help="查看规则应用记录")
    tip_apps.add_argument("--database", type=Path, default=database)
    tip_apps.add_argument("--limit", type=int, default=100)
    tip_batches = tip_actions.add_parser("batches", help="查看技巧应用批次")
    tip_batches.add_argument("--database", type=Path, default=database)
    tip_batches.add_argument("--limit", type=int, default=100)
    tip_rollback = tip_actions.add_parser("rollback", help="恢复应用前的 AGENTS.md")
    tip_rollback.add_argument("application_id", type=int)
    tip_rollback.add_argument("--database", type=Path, default=database)
    tip_rollback_batch = tip_actions.add_parser("rollback-batch", help="整组恢复应用前的 AGENTS.md")
    tip_rollback_batch.add_argument("batch_id")
    tip_rollback_batch.add_argument("--database", type=Path, default=database)
    tip_refresh = tip_actions.add_parser("refresh", help="核验官方技巧来源")
    tip_refresh.add_argument("--database", type=Path, default=database)
    tip_refresh.add_argument("--force", action="store_true")
    tip_refresh.add_argument("--timeout", type=float, default=20)

    daily = actions.add_parser("daily", help="刷新雷达并生成日报")
    daily.add_argument("--database", type=Path, default=database)
    daily.add_argument("--timeout", type=float, default=20)
    daily.add_argument("--force-refresh", action="store_true")
    daily.add_argument("--poster-provider", choices=("openai", "openclaw"))
    daily.add_argument("--output", type=Path)

    poster = actions.add_parser("poster", help="管理纯图片日报")
    poster_actions = poster.add_subparsers(dest="poster_action", required=True)
    generate = poster_actions.add_parser("generate")
    generate.add_argument("--database", type=Path, default=database)
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--provider", choices=("openai", "openclaw"))
    generate.add_argument("--model")
    generate.add_argument("--output", type=Path)
    models = poster_actions.add_parser("models")
    models.add_argument("--database", type=Path, default=database)
    models.add_argument("--json", action="store_true")
    configure = poster_actions.add_parser("configure")
    configure.add_argument("--database", type=Path, default=database)
    configure.add_argument("--provider", choices=("openai", "openclaw"))
    configure.add_argument("--model")
    configure_mode = configure.add_mutually_exclusive_group(required=True)
    configure_mode.add_argument("--enable", action="store_true")
    configure_mode.add_argument("--disable", action="store_true")
    model_test = poster_actions.add_parser("test-model")
    model_test.add_argument("--provider", required=True, choices=("openclaw",))
    model_test.add_argument("--model", required=True)
    model_test.add_argument("--output", required=True, type=Path)
    benchmark = poster_actions.add_parser("benchmark", help="运行或查看本机中文海报基准")
    benchmark.add_argument("benchmark_action", nargs="?", choices=("status", "review"), default="run")
    benchmark.add_argument("--database", type=Path, default=database)
    benchmark.add_argument("--provider", choices=("openclaw",))
    benchmark.add_argument("--model")
    benchmark.add_argument("--cases", type=int, default=3)
    benchmark_review = benchmark.add_mutually_exclusive_group()
    benchmark_review.add_argument("--approve", action="store_true")
    benchmark_review.add_argument("--reject", action="store_true")
    benchmark.add_argument("--notes", default="")
    latest = poster_actions.add_parser("latest")
    latest.add_argument("--database", type=Path, default=database)
    history = poster_actions.add_parser("list")
    history.add_argument("--database", type=Path, default=database)
    history.add_argument("--days", type=int, default=90)
    key = poster_actions.add_parser("key")
    key.add_argument("key_action", choices=("set", "status", "delete"))
    key.add_argument("--database", type=Path, default=database)

    dashboard = actions.add_parser("dashboard", help="启动本地 Dashboard")
    dashboard.add_argument("--port", type=int, default=context.dashboard_port)
    dashboard.add_argument("--database", type=Path, default=database)
    dashboard.add_argument("--open", action="store_true")

    doctor = actions.add_parser("doctor", help="诊断雷达运行状态")
    doctor.add_argument("--database", type=Path, default=database)
    doctor.add_argument("--json", action="store_true")

    site = actions.add_parser("site", help="构建公开只读静态站点")
    site_actions = site.add_subparsers(dest="site_action", required=True)
    site_build = site_actions.add_parser("build", help="导出 GitHub Pages 数据和静态资产")
    site_build.add_argument("--database", type=Path, default=database)
    site_build.add_argument("--output", type=Path, required=True)
    site_build.add_argument(
        "--base-url",
        default="https://ai-resource-radar.github.io/ai-resource-radar/",
        help="站点公开基址（必须是 HTTP(S) URL）",
    )
    site_build.add_argument(
        "--source-revision",
        default=None,
        help="生成该公开快照的源码提交标识",
    )
    site_build.add_argument(
        "--refresh-report",
        type=Path,
        default=None,
        help="本轮 refresh JSON 报告；提供后启用公开数据新鲜度门槛",
    )

    start = actions.add_parser(
        "start",
        help="首次自动采集一次，然后启动本机 Dashboard（uvx 一行体验）",
    )
    start.add_argument("--port", type=int, default=context.dashboard_port)
    start.add_argument("--database", type=Path, default=database)
    start.add_argument("--timeout", type=float, default=20)
    start.add_argument("--open", action="store_true")

    service = actions.add_parser("service", help="管理 macOS 常驻服务")
    service.add_argument("service_action", choices=("install", "status", "uninstall"))
    service.add_argument("--port", type=int, default=context.dashboard_port)
    service.add_argument("--hour", type=int, default=8)
    service.add_argument("--minute", type=int, default=0)
    service.add_argument("--database", type=Path, default=database)
    return parser


def _print(payload: object, *, output: Path | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.write_text(rendered, encoding="utf-8")


def _list_markdown(records: tuple[dict[str, Any], ...]) -> str:
    if not records:
        return "# AI 资源雷达\n\n还没有本地数据，请先运行 `ai-radar refresh`。\n"
    lines = ["# AI 资源雷达", ""]
    for record in records:
        quota = record.get("quota_value")
        quota_text = "额度浮动" if quota is None else f"{quota:g} {record.get('quota_unit') or ''}".strip()
        card = "无需信用卡" if record.get("requires_card") == "no" else "信用卡要求待确认"
        lines.append(
            f"- [{record.get('priority_tier', 'D')}] {record.get('provider', '')} / "
            f"{record.get('title', '')} — {quota_text}；{card}"
        )
    return "\n".join(lines) + "\n"


def _write_text(rendered: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.write_text(rendered, encoding="utf-8")


def _schema_failure(error: UnsupportedSchemaError) -> int:
    print(
        json.dumps(
            {
                "error": "ai_radar_schema_unsupported",
                "database_schema_version": error.database_version,
                "runtime_supported_schema_version": error.supported_version,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None, *, context: CliContext | None = None) -> int:
    context = context or CliContext()
    args = _parser(context).parse_args(argv)
    if args.action == "refresh":
        try:
            report = refresh(
                args.database,
                source_ids=tuple(args.source) if args.source else None,
                timeout=args.timeout,
                force=args.force,
                official_only=args.official_only,
            )
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except (ValueError, OperationLockedError) as exc:
            print(str(exc), file=sys.stderr)
            return 1 if isinstance(exc, OperationLockedError) else 2
        _print(report.to_dict(), output=args.output)
        return 1 if report.failed_count else 0
    if args.action == "list":
        try:
            records = list_offers(
                args.database,
                kind=args.kind,
                verified_only=args.verified_only,
                no_card=args.no_card,
                free_image_generation=args.free_image_generation,
                mainland=(args.mainland,) if args.mainland else None,
                query=args.query,
                limit=args.limit,
                offset=args.offset,
                include_pricing=False,
            )
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.format == "markdown":
            _write_text(_list_markdown(records), args.output)
        else:
            _print(
                {"schema_version": "2.0", "count": len(records), "resources": records},
                output=args.output,
            )
        return 0
    if args.action == "changes":
        try:
            changes = list_changes(args.database, days=args.days, limit=args.limit)
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print(
            {"schema_version": "2.0", "count": len(changes), "changes": changes},
            output=args.output,
        )
        return 0
    if args.action == "tips":
        try:
            seed_initial_tips(args.database)
            if args.tips_action == "list":
                records = list_tips(
                    args.database,
                    status=args.status,
                    category=args.category,
                    query=args.query,
                    limit=args.limit,
                    offset=args.offset,
                )
                _print({"schema_version": "1.0", "count": len(records), "tips": records})
                return 0
            if args.tips_action == "show":
                record = get_tip(args.database, args.tip_id)
                if record is None:
                    print("tip_not_found", file=sys.stderr)
                    return 1
                _print(record)
                return 0
            if args.tips_action in {"import", "add"}:
                source_url = (
                    args.url
                    if args.tips_action == "import"
                    else args.source_url or "https://local.invalid/ai-resource-radar/manual"
                )
                record = add_tip(
                    args.database,
                    title=args.title,
                    category=args.category,
                    summary=args.summary,
                    instruction=args.instruction,
                    source_url=source_url,
                    source_type="manual",
                    example=args.example,
                    constraints=args.constraint,
                    tags=args.tag,
                    risk_level=args.risk,
                )
                _print(record)
                return 0
            if args.tips_action == "approve":
                _print(
                    review_tip(
                        args.database,
                        args.tip_id,
                        action="approve",
                        scope=args.scope,
                        project_root=context.project_root,
                    )
                )
                return 0
            if args.tips_action == "approve-batch":
                _print(
                    approve_tip_batch(
                        args.database,
                        args.tip_ids,
                        scope=args.scope,
                        adopt_existing=args.adopt_existing,
                        project_root=context.project_root,
                    )
                )
                return 0
            if args.tips_action == "reject":
                _print(
                    review_tip(
                        args.database,
                        args.tip_id,
                        action="reject",
                        reason=args.reason,
                    )
                )
                return 0
            if args.tips_action == "applications":
                applications = list_tip_applications(args.database, limit=args.limit)
                _print({"schema_version": "1.0", "applications": applications})
                return 0
            if args.tips_action == "batches":
                batches = list_tip_application_batches(args.database, limit=args.limit)
                _print({"schema_version": "1.0", "batches": batches})
                return 0
            if args.tips_action == "rollback":
                _print(
                    rollback_tip_application(
                        args.database,
                        args.application_id,
                        project_root=context.project_root,
                    )
                )
                return 0
            if args.tips_action == "rollback-batch":
                _print(
                    rollback_tip_batch(
                        args.database,
                        args.batch_id,
                        project_root=context.project_root,
                    )
                )
                return 0
            report = refresh_official_tips(
                args.database, force=args.force, timeout=args.timeout
            )
            _print(report)
            return 1 if report["failed"] else 0
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except (ValueError, OperationLockedError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2 if isinstance(exc, ValueError) else 1
    if args.action == "daily":
        try:
            report = refresh(
                args.database,
                timeout=args.timeout,
                force=args.force_refresh,
            )
            tips = refresh_official_tips(
                args.database,
                timeout=args.timeout,
                force=args.force_refresh,
            )
            poster = generate_daily_poster(
                args.database,
                poster_root=context.poster_root,
                provider=args.poster_provider,
            )
            poster_status = daily_report_status(args.database)
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except OperationLockedError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _print(
            {
                "schema_version": "1.0",
                "refresh": report.to_dict(),
                "tips": tips,
                "poster": poster,
                "poster_status": poster_status,
            },
            output=args.output,
        )
        # Individual source failures are isolated and recorded in the report;
        # they must not make the scheduled daily job look crashed. A configured
        # poster failure remains a real daily-job failure.
        return 0 if poster.get("status") in {"success", "disabled"} else 1
    if args.action == "poster":
        if args.poster_action == "key":
            store = KeychainStore()
            if args.key_action == "set":
                try:
                    store.set(getpass.getpass("OpenAI API Key："))
                except (RuntimeError, ValueError) as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                print("API Key 已写入 macOS 钥匙串。")
            elif args.key_action == "delete":
                print("已删除。" if store.delete() else "未找到凭据。")
            else:
                _print({"configured": store.configured(), "storage": "macOS Keychain"})
            return 0
        if args.poster_action == "models":
            try:
                payload = {
                    "schema_version": "1.1",
                    "models": list_poster_models(args.database),
                }
            except UnsupportedSchemaError as exc:
                return _schema_failure(exc)
            if args.json:
                _print(payload)
            else:
                for item in payload["models"]:
                    flags = ["已配置" if item["configured"] else "未配置"]
                    flags.append(
                        "正式日报可用"
                        if item["formal_poster_eligible"]
                        else f"仅测试：{item['reason']}"
                    )
                    if item["selected"]:
                        flags.append("当前选择")
                    print(f"{item['provider']}/{item['model']} · {' · '.join(flags)}")
            return 0
        if args.poster_action == "configure":
            if (args.provider is None) != (args.model is None):
                print("poster_provider_and_model_required", file=sys.stderr)
                return 2
            if args.enable and (not args.provider or not args.model):
                print("poster_provider_and_model_required", file=sys.stderr)
                return 2
            try:
                payload = configure_poster(
                    args.database,
                    enabled=args.enable,
                    provider=args.provider,
                    model=args.model,
                )
            except UnsupportedSchemaError as exc:
                return _schema_failure(exc)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            _print(payload)
            return 0
        if args.poster_action == "test-model":
            try:
                payload = test_poster_model(
                    provider=args.provider,
                    model=args.model,
                    output=args.output,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _print(payload)
            return 0
        if args.poster_action == "benchmark":
            model_args = {}
            if args.provider:
                model_args["provider"] = args.provider
            if args.model:
                model_args["model"] = args.model
            try:
                if args.benchmark_action == "status":
                    payload = poster_benchmark_status(args.database, **model_args)
                elif args.benchmark_action == "review":
                    if args.approve == args.reject:
                        print("poster_benchmark_review_decision_required", file=sys.stderr)
                        return 2
                    payload = review_poster_benchmark(
                        args.database,
                        approve=args.approve,
                        notes=args.notes,
                        **model_args,
                    )
                else:
                    if args.approve or args.reject:
                        print("poster_benchmark_review_action_required", file=sys.stderr)
                        return 2
                    payload = run_poster_benchmark(
                        args.database,
                        cases=args.cases,
                        poster_root=context.poster_root,
                        **model_args,
                    )
            except UnsupportedSchemaError as exc:
                return _schema_failure(exc)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except (RuntimeError, OperationLockedError) as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _print(payload)
            return 0
        if args.poster_action == "generate":
            try:
                payload = generate_daily_poster(
                    args.database,
                    force=args.force,
                    poster_root=context.poster_root,
                    provider=args.provider,
                    model=args.model,
                )
            except UnsupportedSchemaError as exc:
                return _schema_failure(exc)
            except OperationLockedError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            _print(payload, output=args.output)
            return 0 if payload.get("status") == "success" else 1
        if args.poster_action == "latest":
            try:
                _print(latest_daily_report(args.database))
            except UnsupportedSchemaError as exc:
                return _schema_failure(exc)
            return 0
        try:
            _print(
                {
                    "schema_version": "1.0",
                    "reports": list_daily_reports(args.database, days=args.days),
                }
            )
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        return 0
    if args.action == "doctor":
        report = (
            context.doctor(args.database)
            if context.doctor is not None
            else diagnose(args.database)
        )
        if isinstance(report, dict):
            if args.json:
                _print(report)
            else:
                print(f"AI Resource Radar Doctor: {report.get('overall', 'failed')}")
                for check in report.get("checks", ()):
                    print(
                        f"[{check.get('status', 'failed')}] "
                        f"{check.get('id', 'unknown')}: {check.get('summary', '')}"
                    )
                    if check.get("remediation"):
                        print(f"  修复：{check['remediation']}")
            return int(report.get("exit_code", 2))
        if args.json:
            _print(report.to_dict())
        else:
            print(f"AI Resource Radar Doctor: {report.overall}")
            for check in report.checks:
                print(f"[{check.status}] {check.id}: {check.summary}")
                if check.remediation:
                    print(f"  修复：{check.remediation}")
        return report.exit_code
    if args.action == "site":
        if args.site_action != "build":
            print("site_action_required", file=sys.stderr)
            return 2
        try:
            manifest = build_public_site(
                args.database,
                args.output,
                base_url=args.base_url,
                source_revision=args.source_revision,
                refresh_report=args.refresh_report,
            )
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except (PublicSiteError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1 if isinstance(exc, PublicSiteError) else 2
        _print(manifest)
        return 0
    if args.action == "start":
        if not 1024 <= args.port <= 65535:
            print("invalid_dashboard_port", file=sys.stderr)
            return 2
        if not 1 <= args.timeout <= 120:
            print("timeout_out_of_range", file=sys.stderr)
            return 2
        try:
            snapshot = radar_summary(args.database)
            active = int((snapshot.get("counts") or {}).get("active") or 0)
            if active == 0:
                print("本地还没有有效快照，先执行一次无密钥初始化采集…", file=sys.stderr)
                report = refresh(args.database, timeout=args.timeout, force=True)
                _print({"initial_refresh": report.to_dict()})
                active = int((radar_summary(args.database).get("counts") or {}).get("active") or 0)
                if active == 0:
                    print("initial_refresh_no_active_resources", file=sys.stderr)
                    return 1
        except UnsupportedSchemaError as exc:
            return _schema_failure(exc)
        except (OperationLockedError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 1 if isinstance(exc, OperationLockedError) else 2
        return serve(
            port=args.port,
            database=args.database,
            poster_root=context.poster_root,
            open_browser=args.open,
        )
    if args.action == "dashboard":
        if not 1024 <= args.port <= 65535:
            print("invalid_dashboard_port", file=sys.stderr)
            return 2
        return serve(
            port=args.port,
            database=args.database,
            poster_root=context.poster_root,
            open_browser=args.open,
        )
    service_actions = {"install": install, "status": status, "uninstall": uninstall}
    try:
        result = service_actions[args.service_action](
            port=args.port,
            hour=args.hour,
            minute=args.minute,
            **({"database": args.database} if args.service_action == "install" else {}),
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _print(result.__dict__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
