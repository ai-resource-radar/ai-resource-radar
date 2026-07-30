from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

from ai_resource_radar.dashboard import serve
from ai_resource_radar.paths import default_database_path
from ai_resource_radar.poster import (
    KeychainStore,
    daily_report_status,
    generate_daily_poster,
    latest_daily_report,
    list_daily_reports,
)
from ai_resource_radar.runtime import refresh
from ai_resource_radar.service import install, status, uninstall
from ai_resource_radar.sources import SOURCE_BY_ID
from ai_resource_radar.store import list_changes, list_offers


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-radar",
        description="确定性采集 AI 免费资源与价格，并可生成纯图片日报。",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    refresh_parser = actions.add_parser("refresh", help="刷新本地资源库")
    refresh_parser.add_argument("--database", type=Path, default=default_database_path())
    refresh_parser.add_argument("--source", action="append", choices=tuple(SOURCE_BY_ID))
    refresh_parser.add_argument("--timeout", type=float, default=20)
    refresh_parser.add_argument("--force", action="store_true")
    refresh_parser.add_argument("--official-only", action="store_true")

    list_parser = actions.add_parser("list", help="查看当前资源")
    list_parser.add_argument("--database", type=Path, default=default_database_path())
    list_parser.add_argument("--kind", choices=("token", "gpu", "grant"))
    list_parser.add_argument("--verified-only", action="store_true")
    list_parser.add_argument("--no-card", action="store_true")
    list_parser.add_argument("--mainland", choices=("supported", "unknown", "unsupported"))
    list_parser.add_argument("--query")
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--offset", type=int, default=0)

    changes_parser = actions.add_parser("changes", help="查看变化历史")
    changes_parser.add_argument("--database", type=Path, default=default_database_path())
    changes_parser.add_argument("--days", type=int, default=30)
    changes_parser.add_argument("--limit", type=int, default=100)

    daily = actions.add_parser("daily", help="刷新雷达并生成日报")
    daily.add_argument("--database", type=Path, default=default_database_path())
    daily.add_argument("--timeout", type=float, default=20)
    daily.add_argument("--force-refresh", action="store_true")

    poster = actions.add_parser("poster", help="管理纯图片日报")
    poster_actions = poster.add_subparsers(dest="poster_action", required=True)
    generate = poster_actions.add_parser("generate")
    generate.add_argument("--database", type=Path, default=default_database_path())
    generate.add_argument("--force", action="store_true")
    latest = poster_actions.add_parser("latest")
    latest.add_argument("--database", type=Path, default=default_database_path())
    history = poster_actions.add_parser("list")
    history.add_argument("--database", type=Path, default=default_database_path())
    history.add_argument("--days", type=int, default=90)
    key = poster_actions.add_parser("key")
    key.add_argument("key_action", choices=("set", "status", "delete"))

    dashboard = actions.add_parser("dashboard", help="启动本地 Dashboard")
    dashboard.add_argument("--port", type=int, default=18766)
    dashboard.add_argument("--database", type=Path, default=default_database_path())
    dashboard.add_argument("--open", action="store_true")

    service = actions.add_parser("service", help="管理 macOS 常驻服务")
    service.add_argument("service_action", choices=("install", "status", "uninstall"))
    service.add_argument("--port", type=int, default=18766)
    service.add_argument("--hour", type=int, default=8)
    service.add_argument("--minute", type=int, default=0)
    service.add_argument("--database", type=Path, default=default_database_path())
    return parser


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "refresh":
        try:
            report = refresh(
                args.database,
                source_ids=tuple(args.source) if args.source else None,
                timeout=args.timeout,
                force=args.force,
                official_only=args.official_only,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print(report.to_dict())
        return 1 if report.failed_count else 0
    if args.action == "list":
        try:
            records = list_offers(
                args.database,
                kind=args.kind,
                verified_only=args.verified_only,
                no_card=args.no_card,
                mainland=(args.mainland,) if args.mainland else None,
                query=args.query,
                limit=args.limit,
                offset=args.offset,
                include_pricing=False,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print({"schema_version": "2.0", "count": len(records), "resources": records})
        return 0
    if args.action == "changes":
        try:
            changes = list_changes(args.database, days=args.days, limit=args.limit)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print({"schema_version": "2.0", "count": len(changes), "changes": changes})
        return 0
    if args.action == "daily":
        report = refresh(
            args.database,
            timeout=args.timeout,
            force=args.force_refresh,
        )
        poster = generate_daily_poster(args.database)
        _print(
            {
                "schema_version": "1.0",
                "refresh": report.to_dict(),
                "poster": poster,
                "poster_status": daily_report_status(args.database),
            }
        )
        return 1 if report.failed_count else 0
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
        if args.poster_action == "generate":
            payload = generate_daily_poster(args.database, force=args.force)
            _print(payload)
            return 0 if payload.get("status") == "success" else 1
        if args.poster_action == "latest":
            _print(latest_daily_report(args.database))
            return 0
        _print(
            {
                "schema_version": "1.0",
                "reports": list_daily_reports(args.database, days=args.days),
            }
        )
        return 0
    if args.action == "dashboard":
        if not 1024 <= args.port <= 65535:
            print("invalid_dashboard_port", file=sys.stderr)
            return 2
        return serve(port=args.port, database=args.database, open_browser=args.open)
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
