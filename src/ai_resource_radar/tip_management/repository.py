"""Database-facing tip repository operations."""

from __future__ import annotations

from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable
from urllib.parse import urlparse

from ai_resource_radar.store import connect

from .discovery import OFFICIAL_TIP_SOURCES, TIP_CATEGORIES, TIP_RISK_LEVELS, TIP_SOURCE_TYPES, TIP_STATUSES

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKER = re.compile(r"<!--\s*AI-RADAR-TIPS:(?:BEGIN|END)\s*-->", re.I)


def _legacy_attr(name: str, default: Any) -> Any:
    legacy = sys.modules.get("ai_resource_radar.tip_management.application")
    return getattr(legacy, name, default) if legacy is not None else default


def _connection(path: Path) -> Any:
    return _legacy_attr("connect", connect)(path)


def seed_initial_tips(path: Path) -> dict[str, Any]:
    """Install the user-provided Luna workflow as an unapproved candidate."""

    return add_tip(
        path,
        title="主代理负责思考，Luna 子代理并行执行",
        category="delegation",
        summary="为已经决定委派的边界清晰任务固定使用 Luna Worker，缩短扫描、核对、测试和隔离小修复的墙钟时间。",
        instruction="当主代理已经按协作原则决定委派时，把边界窄、可独立验证的仓库扫描、官方资料核对、测试执行、日志分诊、重复检查和小型隔离修复交给固定的 gpt-5.6-luna/max。",
        source_url="https://mp.weixin.qq.com/s/-kfOLKgpJYQVo31CxIO0tg",
        source_type="manual",
        source_title="Codex 如何实现“无限额度”/“无限子弹”",
        example="让 Luna Worker 只扫描指定目录中的未处理 TODO，返回文件、行号和验证结果，不修改其他文件。",
        constraints=(
            "Luna Worker 固定使用 gpt-5.6-luna/max，不为简单任务临时改成其他模型。",
            "严格执行主代理已经划定的范围和文件所有权，不扩展需求或改动无关文件。",
            "能验证时运行目标检查，只返回结论、文件路径、验证结果和重要限制，不回传原始日志噪声。",
            "Luna 用于明确执行工作，不替代主代理的需求澄清、架构取舍、权限判断和最终验收。",
        ),
        tags=("codex", "luna", "subagents", "parallel"),
        evidence_summary="用户提供的公众号文章摘要；属于社区技巧，必须人工批准后才能应用。",
        risk_level="medium",
    )


def _now(value: datetime | None = None) -> str:
    return (value or datetime.now().astimezone()).astimezone().isoformat(
        timespec="seconds"
    )


def _clean_text(value: Any, *, field: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid_tip_{field}")
    output = _CONTROL.sub("", html.unescape(value)).replace("\r", "").strip()
    output = _MARKER.sub("", output)
    if required and not output:
        raise ValueError(f"invalid_tip_{field}")
    if len(output) > limit:
        raise ValueError(f"tip_{field}_too_long")
    return output


def _clean_items(values: Iterable[Any] | None, *, field: str, limit: int) -> tuple[str, ...]:
    output: list[str] = []
    for value in values or ():
        item = _clean_text(value, field=field, limit=limit)
        if item not in output:
            output.append(item)
        if len(output) >= 12:
            break
    return tuple(output)


def _validate_source_url(value: str) -> str:
    source_url = _clean_text(value, field="source_url", limit=2048)
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("tip_source_must_be_https")
    return source_url


def _tip_payload(
    *,
    title: str,
    category: str,
    summary: str,
    instruction: str,
    example: str,
    constraints: tuple[str, ...],
    tags: tuple[str, ...],
    risk_level: str,
    source_type: str,
    source_url: str,
    source_title: str,
    evidence_summary: str,
) -> dict[str, Any]:
    if category not in TIP_CATEGORIES:
        raise ValueError("invalid_tip_category")
    if risk_level not in TIP_RISK_LEVELS:
        raise ValueError("invalid_tip_risk_level")
    if source_type not in TIP_SOURCE_TYPES:
        raise ValueError("invalid_tip_source_type")
    return {
        "title": _clean_text(title, field="title", limit=160),
        "category": category,
        "summary": _clean_text(summary, field="summary", limit=600),
        "instruction": _clean_text(instruction, field="instruction", limit=1600),
        "example": _clean_text(example, field="example", limit=1200, required=False),
        "constraints": constraints,
        "tags": tags,
        "risk_level": risk_level,
        "source_type": source_type,
        "source_url": _validate_source_url(source_url),
        "source_title": _clean_text(
            source_title, field="source_title", limit=240, required=False
        ),
        "evidence_summary": _clean_text(
            evidence_summary, field="evidence", limit=800, required=False
        ),
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _tip_id(payload: dict[str, Any]) -> str:
    source = f"{payload['source_url']}\n{payload['title']}".encode("utf-8")
    return "tip-" + hashlib.sha256(source).hexdigest()[:20]


def add_tip(
    path: Path,
    *,
    title: str,
    category: str,
    summary: str,
    instruction: str,
    source_url: str,
    source_type: str = "manual",
    source_title: str = "",
    example: str = "",
    constraints: Iterable[str] = (),
    tags: Iterable[str] = (),
    evidence_summary: str = "",
    risk_level: str = "medium",
    now: datetime | None = None,
) -> dict[str, Any]:
    clean_constraints = _clean_items(constraints, field="constraint", limit=400)
    clean_tags = _clean_items(tags, field="tag", limit=60)
    payload = _tip_payload(
        title=title,
        category=category,
        summary=summary,
        instruction=instruction,
        example=example,
        constraints=clean_constraints,
        tags=clean_tags,
        risk_level=risk_level,
        source_type=source_type,
        source_url=source_url,
        source_title=source_title,
        evidence_summary=evidence_summary,
    )
    fingerprint = _payload_hash(payload)
    tip_id = _tip_id(payload)
    at = _now(now)
    connection = _connection(path)
    try:
        existing = connection.execute(
            "SELECT content_hash, status FROM tips WHERE tip_id = ?", (tip_id,)
        ).fetchone()
        if existing and str(existing["content_hash"]) == fingerprint:
            result = get_tip(path, tip_id)
            assert result is not None
            return result
        with connection:
            connection.execute(
                """
                INSERT INTO tips(
                    tip_id, title, category, summary, instruction, example,
                    constraints_json, tags_json, status, risk_level,
                    source_type, source_url, source_title, evidence_summary,
                    content_hash, discovered_at, verified_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tip_id) DO UPDATE SET
                    title = excluded.title, category = excluded.category,
                    summary = excluded.summary, instruction = excluded.instruction,
                    example = excluded.example,
                    constraints_json = excluded.constraints_json,
                    tags_json = excluded.tags_json,
                    risk_level = excluded.risk_level,
                    source_title = excluded.source_title,
                    evidence_summary = excluded.evidence_summary,
                    content_hash = excluded.content_hash,
                    verified_at = excluded.verified_at,
                    updated_at = excluded.updated_at,
                    status = CASE WHEN tips.status = 'approved' THEN 'candidate' ELSE tips.status END,
                    reviewed_at = CASE WHEN tips.status = 'approved' THEN NULL ELSE tips.reviewed_at END,
                    approved_at = CASE WHEN tips.status = 'approved' THEN NULL ELSE tips.approved_at END
                """,
                (
                    tip_id,
                    payload["title"],
                    payload["category"],
                    payload["summary"],
                    payload["instruction"],
                    payload["example"],
                    json.dumps(payload["constraints"], ensure_ascii=False),
                    json.dumps(payload["tags"], ensure_ascii=False),
                    payload["risk_level"],
                    payload["source_type"],
                    payload["source_url"],
                    payload["source_title"],
                    payload["evidence_summary"],
                    fingerprint,
                    at,
                    at if source_type == "official" else None,
                    at,
                    at,
                ),
            )
            connection.execute(
                """
                INSERT INTO tip_evidence(
                    tip_id, source_url, source_type, fetched_at, content_hash,
                    evidence_summary, parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, 'success')
                """,
                (
                    tip_id,
                    payload["source_url"],
                    payload["source_type"],
                    at,
                    fingerprint,
                    payload["evidence_summary"],
                ),
            )
            connection.execute(
                """
                INSERT INTO tip_changes(
                    tip_id, changed_at, change_type, after_json, importance
                ) VALUES (?, ?, ?, ?, 'normal')
                """,
                (
                    tip_id,
                    at,
                    "added" if existing is None else "updated",
                    json.dumps(
                        {"content_hash": fingerprint, "status": "candidate"},
                        separators=(",", ":"),
                    ),
                ),
            )
        result = get_tip(path, tip_id)
        assert result is not None
        return result
    finally:
        connection.close()


def _row_tip(row: Any) -> dict[str, Any]:
    output = dict(row)
    output["constraints"] = json.loads(output.pop("constraints_json") or "[]")
    output["tags"] = json.loads(output.pop("tags_json") or "[]")
    return output


def get_tip(path: Path, tip_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    connection = _connection(path)
    try:
        row = connection.execute("SELECT * FROM tips WHERE tip_id = ?", (tip_id,)).fetchone()
        if row is None:
            return None
        output = _row_tip(row)
        output["applications"] = [
            dict(item)
            for item in connection.execute(
                "SELECT * FROM tip_applications WHERE tip_id = ? ORDER BY id DESC",
                (tip_id,),
            ).fetchall()
        ]
        return output
    finally:
        connection.close()


def list_tips(
    path: Path,
    *,
    status: str | None = None,
    category: str | None = None,
    risk: str | None = None,
    source: str | None = None,
    scope: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[dict[str, Any], ...]:
    if status is not None and status not in TIP_STATUSES:
        raise ValueError("invalid_tip_status")
    if category is not None and category not in TIP_CATEGORIES:
        raise ValueError("invalid_tip_category")
    if risk is not None and risk not in TIP_RISK_LEVELS:
        raise ValueError("invalid_tip_risk_level")
    if source is not None and source not in TIP_SOURCE_TYPES:
        raise ValueError("invalid_tip_source_type")
    if scope is not None and scope not in {"global", "project"}:
        raise ValueError("invalid_tip_scope")
    if not 1 <= limit <= 500 or not 0 <= offset <= 100_000:
        raise ValueError("invalid_tip_pagination")
    if not path.exists():
        return ()
    clauses = ["1 = 1"]
    values: list[Any] = []
    for column, value in (
        ("status", status),
        ("category", category),
        ("risk_level", risk),
        ("source_type", source),
    ):
        if value is not None:
            clauses.append(f"t.{column} = ?")
            values.append(value)
    if scope:
        clauses.append(
            "EXISTS (SELECT 1 FROM tip_applications a WHERE a.tip_id = t.tip_id "
            "AND a.scope = ? AND a.status = 'applied')"
        )
        values.append(scope)
    if query:
        token = f"%{_clean_text(query, field='query', limit=100)}%"
        clauses.append("(t.title LIKE ? OR t.summary LIKE ? OR t.tags_json LIKE ?)")
        values.extend((token, token, token))
    values.extend((limit, offset))
    connection = _connection(path)
    try:
        rows = connection.execute(
            f"""
            SELECT t.* FROM tips t
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE t.status WHEN 'approved' THEN 0 WHEN 'candidate' THEN 1
                     WHEN 'rejected' THEN 2 ELSE 3 END,
                     CASE t.risk_level WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     t.updated_at DESC, t.title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            values,
        ).fetchall()
        return tuple(_row_tip(row) for row in rows)
    finally:
        connection.close()


def tips_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "1.0",
            "counts": {status: 0 for status in TIP_STATUSES},
            "applied": {"global": 0, "project": 0},
            "sources": {"total": len(OFFICIAL_TIP_SOURCES), "healthy": 0, "failed": 0, "items": []},
            "last_updated_at": None,
        }
    connection = _connection(path)
    try:
        counts = {
            status: int(
                connection.execute(
                    "SELECT COUNT(*) FROM tips WHERE status = ?", (status,)
                ).fetchone()[0]
            )
            for status in TIP_STATUSES
        }
        applied = {
            scope: int(
                connection.execute(
                    "SELECT COUNT(DISTINCT tip_id) FROM tip_applications "
                    "WHERE scope = ? AND status = 'applied'",
                    (scope,),
                ).fetchone()[0]
            )
            for scope in ("global", "project")
        }
        updated = connection.execute("SELECT MAX(updated_at) FROM tips").fetchone()[0]
        source_items: list[dict[str, Any]] = []
        current = datetime.now().astimezone()
        for source_item in OFFICIAL_TIP_SOURCES:
            prefix = f"tips.source.{source_item.source_id}."
            metadata = {
                str(row["key"])[len(prefix):]: str(row["value"])
                for row in connection.execute(
                    "SELECT key, value FROM radar_metadata WHERE key LIKE ?",
                    (prefix + "%",),
                ).fetchall()
            }
            last_success = metadata.get("last_success_at")
            error = metadata.get("last_error") or None
            status = "never"
            if error:
                status = "verification_pending" if "verification_pending" in error else "failed"
            elif last_success:
                try:
                    parsed = datetime.fromisoformat(last_success)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=current.tzinfo)
                    age = (current - parsed.astimezone(current.tzinfo)).total_seconds() / 3600
                    status = "fresh" if age <= 174 else "overdue" if age <= 336 else "stale"
                except ValueError:
                    status = "never"
            source_items.append(
                {
                    "source_id": source_item.source_id,
                    "title": source_item.title,
                    "status": status,
                    "last_success_at": last_success,
                    "error_code": error,
                }
            )
        return {
            "schema_version": "1.0",
            "counts": counts,
            "applied": applied,
            "sources": {
                "total": len(source_items),
                "healthy": sum(item["status"] == "fresh" for item in source_items),
                "failed": sum(item["status"] in {"failed", "verification_pending"} for item in source_items),
                "items": source_items,
            },
            "last_updated_at": updated,
        }
    finally:
        connection.close()




__all__ = [
    "OFFICIAL_TIP_SOURCES",
    "TIP_CATEGORIES",
    "TIP_RISK_LEVELS",
    "TIP_SOURCE_TYPES",
    "TIP_STATUSES",
    "_clean_items",
    "_clean_text",
    "_now",
    "_payload_hash",
    "_tip_id",
    "_tip_payload",
    "_validate_source_url",
    "add_tip",
    "get_tip",
    "list_tips",
    "seed_initial_tips",
    "tips_summary",
]
