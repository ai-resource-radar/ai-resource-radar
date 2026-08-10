from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ai_resource_radar.locks import operation_lock
from ai_resource_radar.sources import (
    RadarSource,
    SOURCES,
    SOURCE_BY_ID,
    parse_source,
)
from ai_resource_radar.store import (
    begin_run,
    connect,
    enqueue_digest,
    finish_failure,
    finish_not_modified,
    finish_skipped,
    ingest_source,
    maintain_storage,
    source_cache,
    source_is_due,
)


MAX_SOURCE_BYTES = 16 * 1024 * 1024
USER_AGENT = "AIResourceRadar/0.6"


@dataclass(frozen=True)
class FetchPayload:
    status: int
    body: bytes
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class RefreshSourceResult:
    source_id: str
    status: str
    item_count: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "item_count": self.item_count,
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class RefreshReport:
    generated_at: str
    sources: tuple[RefreshSourceResult, ...]
    notification_id: int | None = None
    maintenance: dict[str, Any] | None = None
    schema_version: str = "2.0"

    @property
    def failed_count(self) -> int:
        return sum(
            item.status in {"failed", "verification_pending"} for item in self.sources
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "summary": {
                "source_count": len(self.sources),
                "successful": sum(
                    item.status in {"success", "not_modified", "skipped_not_due"}
                    for item in self.sources
                ),
                "failed": self.failed_count,
                "added": sum(item.added for item in self.sources),
                "updated": sum(item.updated for item in self.sources),
                "removed": sum(item.removed for item in self.sources),
                "notification_id": self.notification_id,
            },
            "sources": [item.to_dict() for item in self.sources],
            "maintenance": self.maintenance or {
                "status": "not_run",
                "pruned_fetch_runs": 0,
                "pruned_changes": 0,
                "pruned_notifications": 0,
                "pruned_offers": 0,
                "pruned_tip_evidence": 0,
                "pruned_tip_changes": 0,
                "pruned_tips": 0,
                "vacuum_status": "not_needed",
                "database_bytes": 0,
                "error_code": None,
            },
        }


Fetcher = Callable[[RadarSource, str | None, str | None, float], Any]


def fetch_source(
    source: RadarSource,
    etag: str | None,
    last_modified: str | None,
    timeout: float,
) -> FetchPayload:
    parsed = urlparse(source.url)
    if parsed.scheme != "https" or parsed.hostname not in source.allowed_hosts:
        raise ValueError("source_not_allowlisted")
    accept = "application/json" if source.format == "json" else "text/html"
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    request = Request(source.url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_SOURCE_BYTES:
                raise ValueError("source_too_large")
            body = response.read(MAX_SOURCE_BYTES + 1)
            if len(body) > MAX_SOURCE_BYTES:
                raise ValueError("source_too_large")
            return FetchPayload(
                status=int(response.status),
                body=body,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except HTTPError as exc:
        if exc.code == 304:
            return FetchPayload(304, b"", etag, last_modified)
        raise OSError(f"http_status_{exc.code}") from exc


def _error_code(exc: Exception, stage: str) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ValueError):
        value = str(exc)
        if value and len(value) <= 80 and value.replace("_", "").isalnum():
            return value
        return f"{stage}_invalid_data"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return f"{stage}_failed"


def _refresh_unlocked(
    path: Path,
    *,
    source_ids: tuple[str, ...] | None = None,
    timeout: float = 20.0,
    force: bool = False,
    official_only: bool = False,
    now: datetime | None = None,
    fetcher: Fetcher = fetch_source,
) -> RefreshReport:
    if not 1 <= timeout <= 120:
        raise ValueError("timeout_out_of_range")
    current = (now or datetime.now().astimezone()).astimezone()
    generated_at = current.isoformat(timespec="seconds")
    selected_ids = source_ids or tuple(source.id for source in SOURCES)
    unknown = sorted(set(selected_ids) - set(SOURCE_BY_ID))
    if unknown:
        raise ValueError(f"unknown_sources:{','.join(unknown)}")
    selected = [
        SOURCE_BY_ID[source_id]
        for source_id in selected_ids
        if not official_only or SOURCE_BY_ID[source_id].authority != "community"
    ]
    results: list[RefreshSourceResult] = []
    connection = connect(path)
    try:
        for source in selected:
            cache = source_cache(connection, source.id)
            if not source_is_due(cache, now=current, force=force):
                finish_skipped(connection, source.id, generated_at)
                results.append(RefreshSourceResult(source.id, "skipped_not_due"))
                continue
            run_id, baseline = begin_run(connection, source.id, generated_at)
            try:
                response = fetcher(
                    source,
                    str(cache["etag"]) if cache and cache["etag"] else None,
                    str(cache["last_modified"])
                    if cache and cache["last_modified"]
                    else None,
                    timeout,
                )
                if int(response.status) == 304:
                    count = finish_not_modified(
                        connection,
                        source_id=source.id,
                        run_id=run_id,
                        at=generated_at,
                    )
                    results.append(
                        RefreshSourceResult(
                            source.id, "not_modified", item_count=count
                        )
                    )
                    continue
                if int(response.status) != 200:
                    raise OSError("unexpected_http_status")
            except Exception as exc:
                error = _error_code(exc, "fetch")
                finish_failure(
                    connection,
                    source_id=source.id,
                    run_id=run_id,
                    at=generated_at,
                    error_code=error,
                    verification_pending=False,
                )
                results.append(
                    RefreshSourceResult(source.id, "failed", error_code=error)
                )
                continue
            try:
                observations = parse_source(source, bytes(response.body))
            except Exception as exc:
                error = _error_code(exc, "parse")
                pending = source.authority != "community"
                finish_failure(
                    connection,
                    source_id=source.id,
                    run_id=run_id,
                    at=generated_at,
                    error_code=error,
                    verification_pending=pending,
                )
                results.append(
                    RefreshSourceResult(
                        source.id,
                        "verification_pending" if pending else "failed",
                        error_code=error,
                    )
                )
                continue
            content_hash = hashlib.sha256(bytes(response.body)).hexdigest()
            added, updated, removed = ingest_source(
                connection,
                source=source,
                observations=observations,
                at=generated_at,
                run_id=run_id,
                http_status=200,
                etag=getattr(response, "etag", None),
                last_modified=getattr(response, "last_modified", None),
                content_hash=content_hash,
                baseline=baseline,
            )
            results.append(
                RefreshSourceResult(
                    source.id,
                    "success",
                    item_count=len(observations),
                    added=added,
                    updated=updated,
                    removed=removed,
                )
            )
        notification_id = enqueue_digest(connection, at=generated_at)
        maintenance = maintain_storage(connection, now=current).to_dict()
    finally:
        connection.close()
    return RefreshReport(
        generated_at=generated_at,
        sources=tuple(results),
        notification_id=notification_id,
        maintenance=maintenance,
    )


def refresh(
    path: Path,
    *,
    source_ids: tuple[str, ...] | None = None,
    timeout: float = 20.0,
    force: bool = False,
    official_only: bool = False,
    now: datetime | None = None,
    fetcher: Fetcher = fetch_source,
) -> RefreshReport:
    """Refresh selected sources while holding the cross-process DB lock."""

    with operation_lock(path, "refresh"):
        return _refresh_unlocked(
            path,
            source_ids=source_ids,
            timeout=timeout,
            force=force,
            official_only=official_only,
            now=now,
            fetcher=fetcher,
        )
