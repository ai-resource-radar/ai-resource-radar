from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ai_resource_radar.locks import operation_lock
from ai_resource_radar.store import connect

from .discovery import (
    MAX_TIP_SOURCE_BYTES,
    MANAGED_BEGIN,
    MANAGED_END,
    OFFICIAL_TIP_SOURCES,
    OfficialTipSource,
    TIP_CATEGORIES,
    TIP_RETENTION_DAYS,
    TIP_RISK_LEVELS,
    TIP_SCOPES,
    TIP_SOURCE_TYPES,
    TIP_STATUSES,
    _CONTROL,
    _MARKER,
    _TextExtractor,
    refresh_official_tips,
)
from .repository import (
    _clean_items,
    _clean_text,
    _now,
    _payload_hash,
    _tip_id,
    _tip_payload,
    _validate_source_url,
    add_tip,
    get_tip,
    list_tips,
    seed_initial_tips,
    tips_summary,
)


def _render_managed_tips(connection: Any, scope: str) -> str:
    rows = connection.execute(
        """
        SELECT DISTINCT t.* FROM tips t
        JOIN tip_applications a ON a.tip_id = t.tip_id
        WHERE t.status = 'approved' AND a.scope = ? AND a.status = 'applied'
        ORDER BY t.category, t.title COLLATE NOCASE
        """,
        (scope,),
    ).fetchall()
    lines = [MANAGED_BEGIN, "## Approved AI efficiency techniques", ""]
    for row in rows:
        lines.append(f"### {_clean_text(row['title'], field='title', limit=160)}")
        lines.append("")
        lines.append(f"- {_clean_text(row['instruction'], field='instruction', limit=1600)}")
        constraints = json.loads(row["constraints_json"] or "[]")
        for item in constraints:
            lines.append(f"- Constraint: {_clean_text(item, field='constraint', limit=400)}")
        lines.append(f"- Radar tip id: `{row['tip_id']}`")
        lines.append("")
    lines.append(MANAGED_END)
    return "\n".join(lines) + "\n"


def _replace_managed_block(original: str, rendered: str) -> str:
    begin = original.find(MANAGED_BEGIN)
    end = original.find(MANAGED_END)
    if (begin < 0) != (end < 0) or (begin >= 0 and end < begin):
        raise ValueError("invalid_managed_tip_block")
    if begin >= 0:
        end += len(MANAGED_END)
        suffix = original[end:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        return original[:begin].rstrip() + "\n\n" + rendered + suffix
    return original.rstrip() + ("\n\n" if original.strip() else "") + rendered


def _remove_markdown_section(original: str, heading: str) -> tuple[str, bool]:
    """Remove one exact Markdown section without fuzzy content matching."""

    lines = original.splitlines(keepends=True)
    wanted = heading.strip()
    matches = [index for index, line in enumerate(lines) if line.strip() == wanted]
    if not matches:
        return original, False
    if len(matches) != 1:
        raise ValueError("tip_adoption_section_ambiguous")
    start = matches[0]
    level = len(wanted) - len(wanted.lstrip("#"))
    if level <= 0 or not wanted[level:].startswith(" "):
        raise ValueError("invalid_tip_adoption_heading")
    end = len(lines)
    heading_pattern = re.compile(r"^(#{1,6})\s+")
    for index in range(start + 1, len(lines)):
        match = heading_pattern.match(lines[index].lstrip())
        if match and len(match.group(1)) <= level:
            end = index
            break
    content = "".join(lines[:start] + lines[end:]).strip()
    return (content + "\n" if content else ""), True


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _backup_root(home: Path) -> Path:
    return home / ".codex" / "backups" / "ai-tips"


def _safe_target(*, scope: str, project_root: Path, home: Path) -> Path:
    if scope == "global":
        candidate = home / ".codex" / "AGENTS.md"
    elif scope == "project":
        candidate = project_root.resolve() / "AGENTS.md"
    else:
        raise ValueError("invalid_tip_scope")
    if candidate.is_symlink():
        raise ValueError("tip_application_symlink_not_allowed")
    return candidate.resolve()


def _write_atomic(target: Path, content: str, *, backup_root: Path, stamp: str) -> tuple[str | None, str, str | None]:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    old = target.read_bytes() if target.exists() else b""
    old_hash = _file_hash(old) if target.exists() else None
    backup_path: Path | None = None
    if target.exists():
        folder = backup_root / stamp
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        label = hashlib.sha256(str(target).encode()).hexdigest()[:12]
        backup_path = folder / f"{label}-AGENTS.md"
        backup_path.write_bytes(old)
        os.chmod(backup_path, 0o600)
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
    descriptor, name = tempfile.mkstemp(prefix=".ai-tips-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return old_hash, _file_hash(content.encode("utf-8")), str(backup_path) if backup_path else None


def review_tip(
    path: Path,
    tip_id: str,
    *,
    action: str,
    scope: str | None = None,
    reason: str = "",
    project_root: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if action not in {"approve", "reject"}:
        raise ValueError("invalid_tip_review_action")
    if action == "approve" and scope not in TIP_SCOPES:
        raise ValueError("tip_scope_required")
    if action == "reject" and scope is not None:
        raise ValueError("tip_reject_does_not_accept_scope")
    at = _now(now)
    root = (project_root or Path.cwd()).resolve()
    user_home = (home or Path.home()).resolve()
    with operation_lock(path, "tips"):
        connection = connect(path)
        try:
            row = connection.execute("SELECT * FROM tips WHERE tip_id = ?", (tip_id,)).fetchone()
            if row is None:
                raise ValueError("tip_not_found")
            if str(row["status"]) != "candidate":
                raise ValueError("tip_not_candidate")
            if action == "reject":
                clean_reason = _clean_text(reason, field="reason", limit=500, required=False)
                with connection:
                    connection.execute(
                        "UPDATE tips SET status = 'rejected', reviewed_at = ?, updated_at = ? WHERE tip_id = ?",
                        (at, at, tip_id),
                    )
                    connection.execute(
                        "INSERT INTO tip_changes(tip_id, changed_at, change_type, before_json, after_json, importance) VALUES (?, ?, 'rejected', ?, ?, 'normal')",
                        (
                            tip_id,
                            at,
                            json.dumps({"status": row["status"]}, separators=(",", ":")),
                            json.dumps({"status": "rejected", "reason": clean_reason}, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                result = get_tip(path, tip_id)
                assert result is not None
                return result

            scopes = ("global", "project") if scope == "both" else (str(scope),)
            backups: list[tuple[Path, str | None]] = []
            application_ids: list[int] = []
            try:
                for item_scope in scopes:
                    target = _safe_target(scope=item_scope, project_root=root, home=user_home)
                    original = target.read_text(encoding="utf-8") if target.exists() else ""
                    # Mark the future application active before rendering, within
                    # the same DB transaction. If any write fails, the transaction
                    # and already-written files are rolled back below.
                    cursor = connection.execute(
                        "INSERT INTO tip_applications(tip_id, scope, target_path, tip_version_hash, status, applied_at) VALUES (?, ?, ?, ?, 'applied', ?)",
                        (tip_id, item_scope, str(target), row["content_hash"], at),
                    )
                    application_ids.append(int(cursor.lastrowid))
                    connection.execute(
                        "UPDATE tips SET status = 'approved', reviewed_at = ?, approved_at = ?, updated_at = ? WHERE tip_id = ?",
                        (at, at, at, tip_id),
                    )
                    rendered = _render_managed_tips(connection, item_scope)
                    content = _replace_managed_block(original, rendered)
                    old_hash, new_hash, backup_path = _write_atomic(
                        target,
                        content,
                        backup_root=_backup_root(user_home),
                        stamp=at.replace(":", "").replace("+", "-").replace("T", "-"),
                    )
                    backups.append((target, backup_path))
                    connection.execute(
                        "UPDATE tip_applications SET old_file_hash = ?, new_file_hash = ?, backup_path = ? WHERE id = ?",
                        (old_hash, new_hash, backup_path, application_ids[-1]),
                    )
                connection.execute(
                    "UPDATE tips SET applied_at = ? WHERE tip_id = ?", (at, tip_id)
                )
                connection.execute(
                    "INSERT INTO tip_changes(tip_id, changed_at, change_type, before_json, after_json, importance) VALUES (?, ?, 'approved', ?, ?, 'high')",
                    (
                        tip_id,
                        at,
                        json.dumps({"status": row["status"]}, separators=(",", ":")),
                        json.dumps({"status": "approved", "scope": scope}, separators=(",", ":")),
                    ),
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                for target, backup_path in reversed(backups):
                    if backup_path and Path(backup_path).exists():
                        shutil.copy2(backup_path, target)
                    else:
                        target.unlink(missing_ok=True)
                error_code = (
                    str(exc)
                    if isinstance(exc, ValueError) and str(exc)
                    else "tip_application_failed"
                )[:120]
                with connection:
                    for item_scope in scopes:
                        target = (
                            user_home / ".codex" / "AGENTS.md"
                            if item_scope == "global"
                            else root / "AGENTS.md"
                        )
                        connection.execute(
                            "INSERT INTO tip_applications(tip_id, scope, target_path, tip_version_hash, status, error_code, applied_at) VALUES (?, ?, ?, ?, 'failed', ?, ?)",
                            (
                                tip_id,
                                item_scope,
                                str(target),
                                row["content_hash"],
                                error_code,
                                at,
                            ),
                        )
                    connection.execute(
                        "INSERT INTO tip_changes(tip_id, changed_at, change_type, after_json, importance) VALUES (?, ?, 'application_failed', ?, 'high')",
                        (
                            tip_id,
                            at,
                            json.dumps(
                                {"scope": scope, "error_code": error_code},
                                separators=(",", ":"),
                            ),
                        ),
                    )
                raise
            result = get_tip(path, tip_id)
            assert result is not None
            return result
        finally:
            connection.close()


def list_tip_applications(path: Path, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 500:
        raise ValueError("invalid_tip_application_limit")
    if not path.exists():
        return ()
    connection = connect(path)
    try:
        return tuple(
            dict(row)
            for row in connection.execute(
                """
                SELECT a.*, t.title FROM tip_applications a
                JOIN tips t ON t.tip_id = a.tip_id
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
    finally:
        connection.close()


def rollback_tip_application(
    path: Path,
    application_id: int,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    at = _now(now)
    root = (project_root or Path.cwd()).resolve()
    user_home = (home or Path.home()).resolve()
    with operation_lock(path, "tips"):
        connection = connect(path)
        try:
            row = connection.execute(
                "SELECT * FROM tip_applications WHERE id = ?", (application_id,)
            ).fetchone()
            if row is None:
                raise ValueError("tip_application_not_found")
            if row["status"] != "applied":
                raise ValueError("tip_application_not_active")
            expected = _safe_target(
                scope=str(row["scope"]), project_root=root, home=user_home
            )
            target = Path(str(row["target_path"])).resolve()
            if target != expected:
                raise ValueError("tip_application_target_mismatch")
            current_hash = _file_hash(target.read_bytes()) if target.exists() else None
            if current_hash != row["new_file_hash"]:
                raise ValueError("tip_application_target_changed")
            backup = Path(str(row["backup_path"])).resolve() if row["backup_path"] else None
            if backup is not None:
                safe_root = _backup_root(user_home).resolve()
                if safe_root not in backup.parents or not backup.is_file():
                    raise ValueError("tip_application_backup_unavailable")
                original = backup.read_bytes()
                descriptor, name = tempfile.mkstemp(prefix=".ai-tips-rollback-", dir=target.parent)
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if target.exists():
                        os.chmod(temporary, target.stat().st_mode & 0o777)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
            with connection:
                connection.execute(
                    "UPDATE tip_applications SET status = 'rolled_back', rolled_back_at = ? WHERE id = ?",
                    (at, application_id),
                )
                connection.execute(
                    "INSERT INTO tip_changes(tip_id, changed_at, change_type, before_json, after_json, importance) VALUES (?, ?, 'rolled_back', ?, ?, 'high')",
                    (
                        row["tip_id"],
                        at,
                        json.dumps({"application_id": application_id, "status": "applied"}, separators=(",", ":")),
                        json.dumps({"application_id": application_id, "status": "rolled_back"}, separators=(",", ":")),
                    ),
                )
            return dict(
                connection.execute(
                    "SELECT * FROM tip_applications WHERE id = ?", (application_id,)
                ).fetchone()
            )
        finally:
            connection.close()


def approve_tip_batch(
    path: Path,
    tip_ids: Iterable[str],
    *,
    scope: str,
    adopt_existing: bool = False,
    project_root: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Approve and apply several candidate tips as one recoverable batch."""

    identifiers = tuple(
        dict.fromkeys(str(item).strip() for item in tip_ids if str(item).strip())
    )
    if not identifiers or len(identifiers) > 12:
        raise ValueError("invalid_tip_batch_size")
    if scope not in TIP_SCOPES:
        raise ValueError("tip_scope_required")
    at = _now(now)
    root = (project_root or Path.cwd()).resolve()
    user_home = (home or Path.home()).resolve()
    scopes = ("global", "project") if scope == "both" else (scope,)
    batch_id = "tip-batch-" + uuid.uuid4().hex
    stamp = (
        at.replace(":", "").replace("+", "-").replace("T", "-")
        + "-"
        + batch_id[-8:]
    )
    with operation_lock(path, "tips"):
        connection = connect(path)
        backups: list[tuple[Path, str | None]] = []
        target_records: list[dict[str, Any]] = []
        removed_sections: list[dict[str, str]] = []
        try:
            placeholders = ",".join("?" for _ in identifiers)
            rows = connection.execute(
                f"SELECT * FROM tips WHERE tip_id IN ({placeholders})", identifiers
            ).fetchall()
            by_id = {str(row["tip_id"]): row for row in rows}
            if set(by_id) != set(identifiers):
                raise ValueError("tip_not_found")
            if any(str(by_id[item]["status"]) != "candidate" for item in identifiers):
                raise ValueError("tip_not_candidate")

            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO tip_application_batches(
                    batch_id, scope, tip_ids_json, status, applied_at
                ) VALUES (?, ?, ?, 'applied', ?)
                """,
                (batch_id, scope, json.dumps(identifiers, ensure_ascii=False), at),
            )
            connection.executemany(
                """
                UPDATE tips SET status = 'approved', reviewed_at = ?,
                    approved_at = ?, applied_at = ?, updated_at = ?
                WHERE tip_id = ?
                """,
                [(at, at, at, at, tip_id) for tip_id in identifiers],
            )
            for item_scope in scopes:
                target = _safe_target(
                    scope=item_scope, project_root=root, home=user_home
                )
                original = target.read_text(encoding="utf-8") if target.exists() else ""
                adopted = original
                if adopt_existing:
                    heading = (
                        "# Efficient multi-agent orchestration"
                        if item_scope == "global"
                        else "## Delegation and ownership"
                    )
                    adopted, removed = _remove_markdown_section(adopted, heading)
                    if removed:
                        removed_sections.append(
                            {"scope": item_scope, "heading": heading}
                        )
                application_ids: list[int] = []
                for tip_id in identifiers:
                    cursor = connection.execute(
                        """
                        INSERT INTO tip_applications(
                            tip_id, scope, target_path, tip_version_hash, status,
                            applied_at, application_batch_id
                        ) VALUES (?, ?, ?, ?, 'applied', ?, ?)
                        """,
                        (
                            tip_id,
                            item_scope,
                            str(target),
                            by_id[tip_id]["content_hash"],
                            at,
                            batch_id,
                        ),
                    )
                    application_ids.append(int(cursor.lastrowid))
                rendered = _render_managed_tips(connection, item_scope)
                content = _replace_managed_block(adopted, rendered)
                old_hash, new_hash, backup_path = _write_atomic(
                    target,
                    content,
                    backup_root=_backup_root(user_home),
                    stamp=stamp,
                )
                backups.append((target, backup_path))
                target_records.append(
                    {
                        "scope": item_scope,
                        "target_path": str(target),
                        "old_file_hash": old_hash,
                        "new_file_hash": new_hash,
                        "backup_path": backup_path,
                    }
                )
                connection.executemany(
                    """
                    UPDATE tip_applications SET old_file_hash = ?,
                        new_file_hash = ?, backup_path = ? WHERE id = ?
                    """,
                    [
                        (old_hash, new_hash, backup_path, application_id)
                        for application_id in application_ids
                    ],
                )
            connection.execute(
                """
                UPDATE tip_application_batches SET targets_json = ?,
                    removed_sections_json = ? WHERE batch_id = ?
                """,
                (
                    json.dumps(
                        target_records, ensure_ascii=False, separators=(",", ":")
                    ),
                    json.dumps(
                        removed_sections, ensure_ascii=False, separators=(",", ":")
                    ),
                    batch_id,
                ),
            )
            connection.executemany(
                """
                INSERT INTO tip_changes(
                    tip_id, changed_at, change_type, before_json, after_json,
                    importance
                ) VALUES (?, ?, 'approved', ?, ?, 'high')
                """,
                [
                    (
                        tip_id,
                        at,
                        json.dumps({"status": "candidate"}, separators=(",", ":")),
                        json.dumps(
                            {
                                "status": "approved",
                                "scope": scope,
                                "batch_id": batch_id,
                            },
                            separators=(",", ":"),
                        ),
                    )
                    for tip_id in identifiers
                ],
            )
            connection.commit()
            return dict(
                connection.execute(
                    "SELECT * FROM tip_application_batches WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()
            )
        except Exception as exc:
            connection.rollback()
            for target, backup_path in reversed(backups):
                if backup_path and Path(backup_path).is_file():
                    shutil.copy2(backup_path, target)
                else:
                    target.unlink(missing_ok=True)
            error_code = (
                str(exc)
                if isinstance(exc, ValueError) and str(exc)
                else "tip_batch_application_failed"
            )[:120]
            with connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO tip_application_batches(
                        batch_id, scope, tip_ids_json, targets_json,
                        removed_sections_json, status, error_code, applied_at
                    ) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?)
                    """,
                    (
                        batch_id,
                        scope,
                        json.dumps(identifiers, ensure_ascii=False),
                        json.dumps(target_records, ensure_ascii=False),
                        json.dumps(removed_sections, ensure_ascii=False),
                        error_code,
                        at,
                    ),
                )
            raise
        finally:
            connection.close()


def list_tip_application_batches(
    path: Path, *, limit: int = 100
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 500:
        raise ValueError("invalid_tip_application_limit")
    if not path.exists():
        return ()
    connection = connect(path)
    try:
        return tuple(
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM tip_application_batches
                ORDER BY applied_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )
    finally:
        connection.close()


def rollback_tip_batch(
    path: Path,
    batch_id: str,
    *,
    project_root: Path | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    at = _now(now)
    root = (project_root or Path.cwd()).resolve()
    user_home = (home or Path.home()).resolve()
    with operation_lock(path, "tips"):
        connection = connect(path)
        try:
            batch = connection.execute(
                "SELECT * FROM tip_application_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise ValueError("tip_application_batch_not_found")
            if batch["status"] != "applied":
                raise ValueError("tip_application_batch_not_active")
            targets = json.loads(batch["targets_json"] or "[]")
            if not isinstance(targets, list) or not targets:
                raise ValueError("tip_application_backup_unavailable")
            validated: list[tuple[Path, Path | None]] = []
            safe_backup_root = _backup_root(user_home).resolve()
            for item in targets:
                if not isinstance(item, dict):
                    raise ValueError("tip_application_backup_unavailable")
                item_scope = str(item.get("scope") or "")
                expected = _safe_target(
                    scope=item_scope, project_root=root, home=user_home
                )
                target = Path(str(item.get("target_path") or "")).resolve()
                if target != expected:
                    raise ValueError("tip_application_target_mismatch")
                current_hash = _file_hash(target.read_bytes()) if target.exists() else None
                if current_hash != item.get("new_file_hash"):
                    raise ValueError("tip_application_target_changed")
                raw_backup = item.get("backup_path")
                backup = Path(str(raw_backup)).resolve() if raw_backup else None
                if backup is not None and (
                    safe_backup_root not in backup.parents or not backup.is_file()
                ):
                    raise ValueError("tip_application_backup_unavailable")
                validated.append((target, backup))

            for target, backup in validated:
                if backup is None:
                    target.unlink(missing_ok=True)
                    continue
                original = backup.read_bytes()
                descriptor, name = tempfile.mkstemp(
                    prefix=".ai-tips-batch-rollback-", dir=target.parent
                )
                temporary = Path(name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if target.exists():
                        os.chmod(temporary, target.stat().st_mode & 0o777)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            tip_ids = json.loads(batch["tip_ids_json"] or "[]")
            with connection:
                connection.execute(
                    """
                    UPDATE tip_application_batches SET status = 'rolled_back',
                        rolled_back_at = ? WHERE batch_id = ?
                    """,
                    (at, batch_id),
                )
                connection.execute(
                    """
                    UPDATE tip_applications SET status = 'rolled_back',
                        rolled_back_at = ?
                    WHERE application_batch_id = ? AND status = 'applied'
                    """,
                    (at, batch_id),
                )
                connection.executemany(
                    """
                    INSERT INTO tip_changes(
                        tip_id, changed_at, change_type, before_json,
                        after_json, importance
                    ) VALUES (?, ?, 'rolled_back', ?, ?, 'high')
                    """,
                    [
                        (
                            tip_id,
                            at,
                            json.dumps(
                                {"batch_id": batch_id, "status": "applied"},
                                separators=(",", ":"),
                            ),
                            json.dumps(
                                {"batch_id": batch_id, "status": "rolled_back"},
                                separators=(",", ":"),
                            ),
                        )
                        for tip_id in tip_ids
                    ],
                )
            return dict(
                connection.execute(
                    "SELECT * FROM tip_application_batches WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()
            )
        finally:
            connection.close()


def prune_tips(path: Path, *, now: datetime | None = None) -> dict[str, int]:
    if not path.exists():
        return {"evidence": 0, "changes": 0, "tips": 0}
    cutoff = ((now or datetime.now().astimezone()) - timedelta(days=TIP_RETENTION_DAYS)).isoformat(timespec="seconds")
    connection = connect(path)
    try:
        with connection:
            evidence = connection.execute(
                "DELETE FROM tip_evidence WHERE fetched_at < ? AND tip_id IN (SELECT tip_id FROM tips WHERE status != 'approved')",
                (cutoff,),
            ).rowcount
            changes = connection.execute(
                "DELETE FROM tip_changes WHERE changed_at < ? AND importance != 'high'",
                (cutoff,),
            ).rowcount
            tips = connection.execute(
                "DELETE FROM tips WHERE status IN ('candidate', 'rejected', 'retired') AND updated_at < ? AND NOT EXISTS (SELECT 1 FROM tip_changes c WHERE c.tip_id = tips.tip_id AND c.importance = 'high')",
                (cutoff,),
            ).rowcount
        return {"evidence": int(evidence), "changes": int(changes), "tips": int(tips)}
    finally:
        connection.close()
