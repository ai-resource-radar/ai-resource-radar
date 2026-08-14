"""Offer, source-cache, notification and summary repository operations."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from ai_resource_radar.sources import (
    OfferObservation,
    RadarSource,
    SOURCES,
    default_presentations,
    official_guide,
    resolve_modalities,
)
from ai_resource_radar.regions import (
    normalize_country,
    parse_regions,
    resolve_country_filter,
)
from .connection import connect
from .maintenance import (
    ABANDONED_FETCH_RUN_MINUTES,
    CHANGE_RETENTION_DAYS,
    FETCH_RUN_RETENTION_DAYS,
    NOTIFICATION_RETENTION_DAYS,
    POSTER_RETENTION_DAYS,
    storage_summary,
)
from .migrations import _decode_json_list, _json

_VERIFICATION_RANK = {"official_api": 0, "official_page": 1, "community": 2}
_TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
_MAINLAND_RANK = {"supported": 0, "unknown": 1, "unsupported": 2}
_TRISTATE = {"required", "not_required", "unknown"}
_AVAILABILITY_SCOPES = {"global", "restricted", "unknown"}


def _availability_records(observation: OfferObservation) -> tuple[tuple[str, str], ...]:
    """Normalize source availability while preserving legacy mainland facts."""

    raw = observation.availability or (
        {"CN": observation.mainland_status}
        if observation.mainland_status in {"supported", "unsupported"}
        else {}
    )
    if not isinstance(raw, dict):
        raise ValueError("invalid_offer_availability")
    records: list[tuple[str, str]] = []
    for country, status in raw.items():
        if not isinstance(country, str) or not isinstance(status, str):
            raise ValueError("invalid_offer_availability")
        code = normalize_country(country)
        normalized_status = status.strip().casefold()
        if normalized_status not in {"supported", "unsupported"}:
            raise ValueError("invalid_offer_availability")
        records.append((code, normalized_status))
    return tuple(sorted(dict(records).items()))


def _availability_scope(observation: OfferObservation) -> str:
    """Infer restricted scope for legacy mainland evidence when unannotated."""

    scope = observation.availability_scope
    if scope not in _AVAILABILITY_SCOPES:
        raise ValueError("invalid_offer_availability_scope")
    if scope == "unknown" and _availability_records(observation):
        return "restricted"
    return scope


def _presentation_records(
    observation: OfferObservation,
) -> tuple[tuple[str, str, str | None, str | None, str | None, str, str], ...]:
    """Validate optional locale presentation data before persistence."""

    records: list[tuple[str, str, str | None, str | None, str | None, str, str]] = []
    presentations = observation.presentations or default_presentations(
        provider=observation.provider,
        title=observation.title,
        eligibility=observation.eligibility,
    )
    if not isinstance(presentations, dict):
        raise ValueError("invalid_offer_presentation")
    for locale, item in presentations.items():
        if not isinstance(item, dict):
            raise ValueError("invalid_offer_presentation")
        presentation = item.get("presentation", "default")
        title = item.get("title")
        benefit_summary = item.get("benefit_summary")
        eligibility = item.get("eligibility")
        usage_steps = item.get("usage_steps", ())
        limitations = item.get("limitations", ())
        if (
            not isinstance(presentation, str)
            or not presentation.strip()
            or not isinstance(locale, str)
            or not locale.strip()
            or title is not None and not isinstance(title, str)
            or benefit_summary is not None and not isinstance(benefit_summary, str)
            or eligibility is not None and not isinstance(eligibility, str)
            or not isinstance(usage_steps, (list, tuple))
            or not isinstance(limitations, (list, tuple))
            or not all(isinstance(value, str) for value in (*usage_steps, *limitations))
        ):
            raise ValueError("invalid_offer_presentation")
        records.append(
            (
                presentation[:80], locale[:35], title, benefit_summary, eligibility,
                _json(list(usage_steps)), _json(list(limitations)),
            )
        )
    return tuple(records)
def source_cache(
    connection: sqlite3.Connection, source_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT etag, last_modified, last_success_at, cadence_hours
        FROM sources WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()


def source_is_due(
    cache: sqlite3.Row | None, *, now: datetime, force: bool
) -> bool:
    if force or cache is None or not cache["last_success_at"]:
        return True
    try:
        last = datetime.fromisoformat(str(cache["last_success_at"]))
    except ValueError:
        return True
    return now.astimezone() - last.astimezone() >= timedelta(
        hours=int(cache["cadence_hours"])
    )




def begin_run(
    connection: sqlite3.Connection, source_id: str, started_at: str
) -> tuple[int, bool]:
    baseline = (
        connection.execute(
            """
            SELECT COUNT(*) FROM fetch_runs
            WHERE source_id = ? AND status IN ('success', 'not_modified')
            """,
            (source_id,),
        ).fetchone()[0]
        == 0
    )
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_attempt_at = ?
            WHERE source_id = ?
            """,
            (started_at, source_id),
        )
        cursor = connection.execute(
            """
            INSERT INTO fetch_runs(source_id, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (source_id, started_at),
        )
    return int(cursor.lastrowid), baseline


def finish_skipped(
    connection: sqlite3.Connection, source_id: str, at: str
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO fetch_runs(
                source_id, started_at, finished_at, status, item_count
            )
            VALUES (?, ?, ?, 'skipped_not_due', 0)
            """,
            (source_id, at, at),
        )


def finish_not_modified(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: int,
    at: str,
) -> int:
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_success_at = ?, last_error_code = NULL, consecutive_failures = 0
            WHERE source_id = ?
            """,
            (at, source_id),
        )
        connection.execute(
            """
            UPDATE offer_evidence SET observed_at = ?
            WHERE source_id = ? AND is_active = 1
            """,
            (at, source_id),
        )
        connection.execute(
            """
            UPDATE fetch_runs
            SET finished_at = ?, status = 'not_modified', http_status = 304
            WHERE id = ?
            """,
            (at, run_id),
        )
    return int(
        connection.execute(
            """
            SELECT COUNT(*) FROM offer_evidence
            WHERE source_id = ? AND is_active = 1
            """,
            (source_id,),
        ).fetchone()[0]
    )


def finish_failure(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    run_id: int,
    at: str,
    error_code: str,
    verification_pending: bool,
) -> None:
    status = "verification_pending" if verification_pending else "failed"
    with connection:
        connection.execute(
            """
            UPDATE sources
            SET last_error_code = ?, consecutive_failures = consecutive_failures + 1
            WHERE source_id = ?
            """,
            (error_code, source_id),
        )
        connection.execute(
            """
            UPDATE fetch_runs
            SET finished_at = ?, status = ?, error_code = ?
            WHERE id = ?
            """,
            (at, status, error_code, run_id),
        )


def classify_offer(observation: OfferObservation) -> tuple[str, tuple[str, ...]]:
    reasons: list[str] = []
    official = observation.verification_level in {"official_api", "official_page"}
    _, output_modalities = resolve_modalities(
        observation.details,
        output_modalities=observation.output_modalities,
    )
    free_image_generation = (
        observation.offer_type in {"recurring_free", "variable_free"}
        and observation.kind == "token"
        and "image" in output_modalities
    )
    if observation.offer_type == "pricing_reference":
        if official:
            return "D", ("官方价格已核验；不参与免费资源等级",)
        return "D", ("社区维护的价格基线；等待官方逐项核验",)
    if not official:
        return "D", ("仅社区或价格线索，尚未由官方免费规则核验",)
    reasons.append("官方来源已核验")
    if observation.requires_card == "no":
        reasons.append("无需信用卡")
    elif observation.requires_card == "yes":
        reasons.append("需要信用卡")
    else:
        reasons.append("信用卡要求待确认")
    if observation.offer_type == "recurring_free":
        reasons.append("周期性免费额度")
    elif observation.offer_type == "variable_free":
        reasons.append("免费但额度与资源动态变化")
    elif observation.offer_type == "grant":
        reasons.append("需要资格申请")
    if free_image_generation:
        reasons.append("免费图片输出能力已核验")
    if (
        observation.requires_card == "no"
        and observation.offer_type == "recurring_free"
        and observation.quota_value is not None
    ):
        return "A", tuple(reasons)
    if (
        observation.requires_card == "no"
        and observation.offer_type in {"recurring_free", "variable_free"}
    ):
        return "B", tuple(reasons)
    return "C", tuple(reasons)


def _offer_payload(
    observation: OfferObservation, tier: str, reasons: tuple[str, ...]
) -> dict[str, Any]:
    availability_scope = _availability_scope(observation)
    if any(value not in _TRISTATE for value in observation.signup_requirements().values()):
        raise ValueError("invalid_signup_requirement")
    input_modalities, output_modalities = resolve_modalities(
        observation.details,
        input_modalities=observation.input_modalities,
        output_modalities=observation.output_modalities,
    )
    free_image_generation = (
        observation.offer_type in {"recurring_free", "variable_free"}
        and observation.kind == "token"
        and "image" in output_modalities
    )
    return {
        "offer_id": observation.offer_id,
        "provider": observation.provider,
        "title": observation.title,
        "kind": observation.kind,
        "offer_type": observation.offer_type,
        "quota_value": observation.quota_value,
        "quota_unit": observation.quota_unit,
        "reset_period": observation.reset_period,
        "estimated_usd_value": observation.estimated_usd_value,
        "requires_card": observation.requires_card,
        "requires_phone": observation.requires_phone,
        "requires_identity_verification": observation.requires_identity_verification,
        "requires_paid_topup": observation.requires_paid_topup,
        "requires_waitlist": observation.requires_waitlist,
        "requires_organization": observation.requires_organization,
        "signup_requirements": observation.signup_requirements(),
        "eligibility": observation.eligibility,
        "mainland_status": observation.mainland_status,
        "availability_scope": availability_scope,
        "availability": dict(_availability_records(observation)),
        "expires_at": observation.expires_at,
        "homepage_url": observation.homepage_url,
        "verification_level": observation.verification_level,
        "priority_tier": tier,
        "priority_reasons": reasons,
        "details": observation.details,
        "input_modalities": list(input_modalities),
        "output_modalities": list(output_modalities),
        "free_image_generation": free_image_generation,
    }


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key
        for key in before
        if before.get(key) != after.get(key)
    )


def _eligible_change(
    *, change_type: str, tier: str, fields: list[str], baseline: bool
) -> tuple[str, bool]:
    if baseline or tier not in {"A", "B"}:
        return "normal", False
    important_fields = {
        "quota_value",
        "quota_unit",
        "reset_period",
        "requires_card",
        "expires_at",
        "status",
    }
    if change_type in {"added", "removed"}:
        return "high", True
    eligible = bool(set(fields) & important_fields)
    return ("high" if eligible else "normal"), eligible


def ingest_source(
    connection: sqlite3.Connection,
    *,
    source: RadarSource,
    observations: tuple[OfferObservation, ...],
    at: str,
    run_id: int,
    http_status: int,
    etag: str | None,
    last_modified: str | None,
    content_hash: str,
    baseline: bool,
) -> tuple[int, int, int]:
    unique = {item.offer_id: item for item in observations}
    added = updated = removed = 0
    with connection:
        existing_evidence = {
            row["offer_id"]: row
            for row in connection.execute(
                """
                SELECT offer_id, content_hash, missing_success_count, is_active
                FROM offer_evidence WHERE source_id = ?
                """,
                (source.id,),
            )
        }
        for offer_id, observation in unique.items():
            tier, reasons = classify_offer(observation)
            payload = _offer_payload(observation, tier, reasons)
            payload_json = _json(payload)
            fingerprint = hashlib.sha256(payload_json.encode()).hexdigest()
            current = connection.execute(
                "SELECT * FROM offers WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            incoming_rank = _VERIFICATION_RANK[observation.verification_level]
            current_rank = (
                _VERIFICATION_RANK.get(str(current["verification_level"]), 9)
                if current
                else 9
            )
            can_replace = current is None or incoming_rank <= current_rank
            change_type: str | None = None
            fields: list[str] = []
            before_json: str | None = None
            after_json: str | None = None
            if current is None:
                added += 1
                change_type = "added"
            elif current["status"] != "active":
                added += 1
                change_type = "added"
            elif can_replace and current["fingerprint"] != fingerprint:
                before = {
                    key: current[key]
                    for key in (
                        "provider",
                        "title",
                        "kind",
                        "offer_type",
                        "quota_value",
                        "quota_unit",
                        "reset_period",
                        "estimated_usd_value",
                        "requires_card",
                        "requires_phone",
                        "requires_identity_verification",
                        "requires_paid_topup",
                        "requires_waitlist",
                        "requires_organization",
                        "eligibility",
                        "mainland_status",
                        "availability_scope",
                        "expires_at",
                        "homepage_url",
                        "verification_level",
                        "priority_tier",
                    )
                }
                before["input_modalities"] = list(
                    _decode_json_list(current["input_modalities_json"])
                )
                before["output_modalities"] = list(
                    _decode_json_list(current["output_modalities_json"])
                )
                before["free_image_generation"] = bool(
                    current["free_image_generation"]
                )
                before["signup_requirements"] = {
                    "card": {"yes": "required", "no": "not_required"}.get(current["requires_card"], "unknown"),
                    "phone": {"yes": "required", "no": "not_required"}.get(current["requires_phone"], "unknown"),
                    "identity_verification": current["requires_identity_verification"],
                    "paid_topup": current["requires_paid_topup"],
                    "waitlist": current["requires_waitlist"],
                    "organization": current["requires_organization"],
                }
                before["availability"] = {
                    row["country_code"]: row["availability_status"]
                    for row in connection.execute(
                        "SELECT country_code, availability_status FROM offer_availability "
                        "WHERE offer_id = ? ORDER BY country_code",
                        (offer_id,),
                    )
                }
                fields = _changed_fields(before, payload)
                if fields:
                    updated += 1
                    change_type = "updated"
                    before_json = _json(
                        {field: before.get(field) for field in fields}
                    )
                    after_json = _json(
                        {field: payload.get(field) for field in fields}
                    )
            if current is None:
                connection.execute(
                    """
                    INSERT INTO offers(
                        offer_id, provider, title, kind, offer_type, quota_value,
                        quota_unit, reset_period, estimated_usd_value, requires_card,
                        requires_phone, requires_identity_verification,
                        requires_paid_topup, requires_waitlist, requires_organization, eligibility,
                        mainland_status, availability_scope, expires_at,
                        homepage_url, verification_level, priority_tier,
                        priority_reasons_json, details_json, input_modalities_json,
                        output_modalities_json, free_image_generation, fingerprint,
                        status,
                        first_seen_at, last_seen_at, last_changed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?,
                            'active', ?, ?, ?)
                    """,
                    (
                        offer_id,
                        observation.provider,
                        observation.title,
                        observation.kind,
                        observation.offer_type,
                        observation.quota_value,
                        observation.quota_unit,
                        observation.reset_period,
                        observation.estimated_usd_value,
                        observation.requires_card,
                        observation.requires_phone,
                        observation.requires_identity_verification,
                        observation.requires_paid_topup,
                        observation.requires_waitlist,
                        observation.requires_organization,
                        observation.eligibility,
                        observation.mainland_status,
                        payload["availability_scope"],
                        observation.expires_at,
                        observation.homepage_url,
                        observation.verification_level,
                        tier,
                        _json(reasons),
                        _json(observation.details),
                        _json(payload["input_modalities"]),
                        _json(payload["output_modalities"]),
                        int(payload["free_image_generation"]),
                        fingerprint,
                        at,
                        at,
                        at,
                    ),
                )
            elif can_replace:
                connection.execute(
                    """
                    UPDATE offers SET
                        provider = ?, title = ?, kind = ?, offer_type = ?,
                        quota_value = ?, quota_unit = ?, reset_period = ?,
                        estimated_usd_value = ?, requires_card = ?,
                        requires_phone = ?, requires_identity_verification = ?,
                        requires_paid_topup = ?, requires_waitlist = ?,
                        requires_organization = ?, eligibility = ?,
                        mainland_status = ?, availability_scope = ?, expires_at = ?,
                        homepage_url = ?, verification_level = ?,
                        priority_tier = ?, priority_reasons_json = ?,
                        details_json = ?, input_modalities_json = ?,
                        output_modalities_json = ?, free_image_generation = ?,
                        fingerprint = ?, status = 'active',
                        last_seen_at = ?,
                        last_changed_at = CASE WHEN fingerprint != ? OR status != 'active'
                            THEN ? ELSE last_changed_at END
                    WHERE offer_id = ?
                    """,
                    (
                        observation.provider,
                        observation.title,
                        observation.kind,
                        observation.offer_type,
                        observation.quota_value,
                        observation.quota_unit,
                        observation.reset_period,
                        observation.estimated_usd_value,
                        observation.requires_card,
                        observation.requires_phone,
                        observation.requires_identity_verification,
                        observation.requires_paid_topup,
                        observation.requires_waitlist,
                        observation.requires_organization,
                        observation.eligibility,
                        observation.mainland_status,
                        payload["availability_scope"],
                        observation.expires_at,
                        observation.homepage_url,
                        observation.verification_level,
                        tier,
                        _json(reasons),
                        _json(observation.details),
                        _json(payload["input_modalities"]),
                        _json(payload["output_modalities"]),
                        int(payload["free_image_generation"]),
                        fingerprint,
                        at,
                        fingerprint,
                        at,
                        offer_id,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE offers SET last_seen_at = ? WHERE offer_id = ?",
                    (at, offer_id),
                )
            if can_replace:
                connection.execute(
                    "DELETE FROM offer_availability WHERE offer_id = ?", (offer_id,)
                )
                connection.executemany(
                    """
                    INSERT INTO offer_availability(
                        offer_id, country_code, availability_status, source_url,
                        evidence_excerpt, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            offer_id,
                            country,
                            status,
                            observation.source_url,
                            observation.evidence_excerpt[:500],
                            at,
                        )
                        for country, status in _availability_records(observation)
                    ],
                )
                connection.execute(
                    "DELETE FROM offer_presentations WHERE offer_id = ?", (offer_id,)
                )
                connection.executemany(
                    """
                    INSERT INTO offer_presentations(
                        offer_id, presentation, locale, title, benefit_summary,
                        eligibility, usage_steps_json, limitations_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (offer_id, presentation, locale, title, benefit_summary,
                         eligibility, usage_steps_json, limitations_json)
                        for (presentation, locale, title, benefit_summary,
                             eligibility, usage_steps_json, limitations_json)
                        in _presentation_records(observation)
                    ],
                )
            evidence_payload = {
                "source_url": observation.source_url,
                "verification_level": observation.verification_level,
                "evidence_excerpt": observation.evidence_excerpt,
            }
            evidence_hash = hashlib.sha256(_json(evidence_payload).encode()).hexdigest()
            connection.execute(
                """
                INSERT INTO offer_evidence(
                    source_id, offer_id, source_url, verification_level,
                    evidence_excerpt, content_hash, observed_at,
                    missing_success_count, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT(source_id, offer_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    verification_level = excluded.verification_level,
                    evidence_excerpt = excluded.evidence_excerpt,
                    content_hash = excluded.content_hash,
                    observed_at = excluded.observed_at,
                    missing_success_count = 0,
                    is_active = 1
                """,
                (
                    source.id,
                    offer_id,
                    observation.source_url,
                    observation.verification_level,
                    observation.evidence_excerpt[:500],
                    evidence_hash,
                    at,
                ),
            )
            if change_type and not baseline:
                importance, eligible = _eligible_change(
                    change_type=change_type,
                    tier=tier,
                    fields=fields,
                    baseline=baseline,
                )
                connection.execute(
                    """
                    INSERT INTO offer_changes(
                        offer_id, detected_at, change_type, changed_fields_json,
                        before_json, after_json, importance, notification_eligible
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        offer_id,
                        at,
                        change_type,
                        _json(fields),
                        before_json,
                        after_json,
                        importance,
                        1 if eligible else 0,
                    ),
                )
        seen = set(unique)
        for offer_id, evidence in existing_evidence.items():
            if offer_id in seen or not evidence["is_active"]:
                continue
            missing_count = int(evidence["missing_success_count"]) + 1
            connection.execute(
                """
                UPDATE offer_evidence
                SET missing_success_count = ?, observed_at = ?,
                    is_active = CASE WHEN ? >= 2 THEN 0 ELSE 1 END
                WHERE source_id = ? AND offer_id = ?
                """,
                (missing_count, at, missing_count, source.id, offer_id),
            )
            if missing_count < 2:
                continue
            active_count = connection.execute(
                """
                SELECT COUNT(*) FROM offer_evidence
                WHERE offer_id = ? AND is_active = 1
                """,
                (offer_id,),
            ).fetchone()[0]
            offer = connection.execute(
                "SELECT * FROM offers WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            if active_count or offer is None or offer["status"] != "active":
                continue
            removed += 1
            connection.execute(
                """
                UPDATE offers SET status = 'inactive', last_changed_at = ?
                WHERE offer_id = ?
                """,
                (at, offer_id),
            )
            importance, eligible = _eligible_change(
                change_type="removed",
                tier=str(offer["priority_tier"]),
                fields=["status"],
                baseline=baseline,
            )
            if not baseline:
                connection.execute(
                    """
                    INSERT INTO offer_changes(
                        offer_id, detected_at, change_type, changed_fields_json,
                        before_json, after_json, importance, notification_eligible
                    )
                    VALUES (?, ?, 'removed', ?, NULL, NULL, ?, ?)
                    """,
                    (
                        offer_id,
                        at,
                        _json(["status"]),
                        importance,
                        1 if eligible else 0,
                    ),
                )
        connection.execute(
            """
            UPDATE sources SET
                etag = ?, last_modified = ?, last_success_at = ?,
                last_error_code = NULL, consecutive_failures = 0
            WHERE source_id = ?
            """,
            (etag, last_modified, at, source.id),
        )
        connection.execute(
            """
            UPDATE fetch_runs SET
                finished_at = ?, status = 'success', http_status = ?,
                content_hash = ?, item_count = ?
            WHERE id = ?
            """,
            (at, http_status, content_hash, len(unique), run_id),
        )
    return added, updated, removed


def enqueue_digest(connection: sqlite3.Connection, *, at: str) -> int | None:
    rows = connection.execute(
        """
        SELECT c.id, c.change_type, c.offer_id, o.provider, o.title, o.priority_tier
        FROM offer_changes c
        LEFT JOIN offers o ON o.offer_id = c.offer_id
        WHERE c.detected_at = ? AND c.notification_eligible = 1
          AND c.notification_id IS NULL
        ORDER BY CASE o.priority_tier WHEN 'A' THEN 0 ELSE 1 END, c.id
        """,
        (at,),
    ).fetchall()
    if not rows:
        return None
    change_ids = [int(row["id"]) for row in rows]
    dedupe_key = hashlib.sha256(
        ",".join(str(item) for item in change_ids).encode()
    ).hexdigest()
    labels = [
        f"{row['provider']} · {row['title']}"
        for row in rows[:3]
        if row["provider"] and row["title"]
    ]
    suffix = f"；另有 {len(rows) - 3} 条" if len(rows) > 3 else ""
    body = "；".join(labels) + suffix
    with connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO notifications(
                created_at, dedupe_key, title, body, target_url, item_count
            )
            VALUES (?, ?, ?, ?, '/ai-resources.html#changes', ?)
            """,
            (at, dedupe_key, f"AI 资源雷达：{len(rows)} 条重要变化", body, len(rows)),
        )
        if cursor.rowcount == 0:
            return None
        notification_id = int(cursor.lastrowid)
        placeholders = ",".join("?" for _ in change_ids)
        connection.execute(
            f"""
            UPDATE offer_changes SET notification_id = ?
            WHERE id IN ({placeholders})
            """,
            (notification_id, *change_ids),
        )
    return notification_id


def _offer_dict(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    locale: str = "en",
    availability_context: tuple[str, ...] = (),
    strict_region: bool = False,
) -> dict[str, Any]:
    evidence = connection.execute(
        """
        SELECT source_id, source_url, verification_level, evidence_excerpt, observed_at
        FROM offer_evidence
        WHERE offer_id = ? AND is_active = 1
        ORDER BY CASE verification_level
            WHEN 'official_api' THEN 0 WHEN 'official_page' THEN 1 ELSE 2 END,
            observed_at DESC
        LIMIT 1
        """,
        (row["offer_id"],),
    ).fetchone()
    details = (
        official_guide(str(row["provider"]), str(row["offer_type"]))
        if row["verification_level"] in {"official_api", "official_page"}
        and row["offer_type"] != "pricing_reference"
        else {}
    )
    details.update(json.loads(row["details_json"]))
    input_modalities = _decode_json_list(
        row["input_modalities_json"] if "input_modalities_json" in row.keys() else None
    )
    output_modalities = _decode_json_list(
        row["output_modalities_json"] if "output_modalities_json" in row.keys() else None
    )
    resolved_inputs, resolved_outputs = resolve_modalities(
        details,
        input_modalities=input_modalities,
        output_modalities=output_modalities,
    )
    free_image_generation = (
        bool(row["free_image_generation"]) and str(row["kind"]) == "token"
        if "free_image_generation" in row.keys()
        else str(row["kind"]) == "token"
        and str(row["offer_type"]) in {"recurring_free", "variable_free"}
        and "image" in resolved_outputs
    )
    availability_rows = connection.execute(
        """
        SELECT country_code, availability_status, source_url, evidence_excerpt,
               observed_at FROM offer_availability
        WHERE offer_id = ? ORDER BY country_code
        """,
        (row["offer_id"],),
    ).fetchall()
    supported_countries = [
        item["country_code"]
        for item in availability_rows
        if item["availability_status"] == "supported"
    ]
    unsupported_countries = [
        item["country_code"]
        for item in availability_rows
        if item["availability_status"] == "unsupported"
    ]
    availability_status: str | None = None
    if availability_context:
        context = set(availability_context)
        if context & set(unsupported_countries):
            availability_status = "unsupported"
        elif strict_region:
            if context <= set(supported_countries):
                availability_status = "supported"
            elif row["availability_scope"] == "global":
                availability_status = "supported"
            else:
                availability_status = "unknown"
        elif context & set(supported_countries):
            availability_status = "supported"
        elif row["availability_scope"] == "global":
            availability_status = "supported"
        else:
            availability_status = "unknown"
    availability = {
        "scope": row["availability_scope"],
        "supported_countries": supported_countries,
        "unsupported_countries": unsupported_countries,
        "evidence": [
            {
                "country_code": item["country_code"],
                "status": item["availability_status"],
                "source_url": item["source_url"],
                "evidence_excerpt": item["evidence_excerpt"],
                "verified_at": item["observed_at"],
            }
            for item in availability_rows
        ],
    }
    presentations = {
        item["locale"]: {
            "presentation": item["presentation"],
            "title": item["title"],
            "benefit_summary": item["benefit_summary"],
            "eligibility": item["eligibility"],
            "usage_steps": json.loads(item["usage_steps_json"]),
            "limitations": json.loads(item["limitations_json"]),
        }
        for item in connection.execute(
            """
            SELECT presentation, locale, title, benefit_summary, eligibility,
                   usage_steps_json, limitations_json FROM offer_presentations
            WHERE offer_id = ? ORDER BY locale, presentation
            """,
            (row["offer_id"],),
        )
    }
    presentation = presentations.get(locale) or presentations.get("en")
    return {
        "offer_id": row["offer_id"],
        "external_id": row["offer_id"],
        "provider": row["provider"],
        "title": row["title"],
        "kind": row["kind"],
        "offer_type": row["offer_type"],
        "quota_value": row["quota_value"],
        "quota_unit": row["quota_unit"],
        "reset_period": row["reset_period"],
        "estimated_usd_value": row["estimated_usd_value"],
        "requires_card": row["requires_card"],
        "requires_phone": row["requires_phone"],
        "requires_identity_verification": row["requires_identity_verification"],
        "requires_paid_topup": row["requires_paid_topup"],
        "requires_waitlist": row["requires_waitlist"],
        "requires_organization": row["requires_organization"],
        "signup_requirements": {
            "card": {"yes": "required", "no": "not_required"}.get(row["requires_card"], "unknown"),
            "phone": {"yes": "required", "no": "not_required"}.get(row["requires_phone"], "unknown"),
            "identity_verification": row["requires_identity_verification"],
            "paid_topup": row["requires_paid_topup"],
            "waitlist": row["requires_waitlist"],
            "organization": row["requires_organization"],
        },
        "eligibility": row["eligibility"],
        "mainland_status": row["mainland_status"],
        "availability_scope": row["availability_scope"],
        "availability": availability,
        "availability_status": availability_status,
        "expires_at": row["expires_at"],
        "homepage_url": row["homepage_url"],
        "url": row["homepage_url"],
        "verification_level": row["verification_level"],
        "verification_status": row["verification_level"],
        "priority_tier": row["priority_tier"],
        "priority_reasons": json.loads(row["priority_reasons_json"]),
        "input_modalities": list(resolved_inputs),
        "output_modalities": list(resolved_outputs),
        "free_image_generation": free_image_generation,
        "details": details,
        "presentations": presentations,
        "presentation": presentation,
        "status": row["status"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "last_changed_at": row["last_changed_at"],
        "evidence": dict(evidence) if evidence else None,
    }


def list_offers(
    path: Path,
    *,
    kind: str | None = None,
    verified_only: bool = False,
    no_card: bool = False,
    mainland: tuple[str, ...] | None = None,
    country: str | tuple[str, ...] | None = None,
    region: str | tuple[str, ...] | None = None,
    include_unknown_region: bool = False,
    locale: str = "en",
    query: str | None = None,
    free_image_generation: bool = False,
    limit: int = 100,
    offset: int = 0,
    include_inactive: bool = False,
    include_pricing: bool = True,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 500 or not 0 <= offset <= 100_000:
        raise ValueError("invalid_offer_pagination")
    if kind is not None and kind not in {"token", "gpu", "grant"}:
        raise ValueError("invalid_offer_kind")
    if not isinstance(include_unknown_region, bool):
        raise ValueError("invalid_region_filter")
    if not isinstance(locale, str) or not locale.strip() or len(locale) > 35:
        raise ValueError("invalid_offer_locale")
    countries = resolve_country_filter(country=country, region=region)
    region_countries = parse_regions(region) if region is not None else ()
    if mainland and (country is not None or region is not None):
        raise ValueError("country_region_mainland_mutually_exclusive")
    if not path.exists():
        return ()
    connection = connect(path)
    try:
        clauses = ["1 = 1"]
        parameters: list[Any] = []
        if not include_inactive:
            clauses.append("status = 'active'")
        if not include_pricing:
            clauses.append("offer_type != 'pricing_reference'")
        if kind:
            clauses.append("kind = ?")
            parameters.append(kind)
        if verified_only:
            clauses.append("verification_level IN ('official_api', 'official_page')")
        if no_card:
            clauses.append("requires_card = 'no'")
        if free_image_generation:
            clauses.append("free_image_generation = 1")
        if mainland:
            valid = tuple(item for item in mainland if item in _MAINLAND_RANK)
            if not valid:
                raise ValueError("invalid_mainland_filter")
            clauses.append(f"mainland_status IN ({','.join('?' for _ in valid)})")
            parameters.extend(valid)
        if countries and region_countries:
            country_marks = ",".join("?" for _ in countries)
            no_unsupported = (
                "NOT EXISTS (SELECT 1 FROM offer_availability availability "
                "WHERE availability.offer_id = offers.offer_id "
                f"AND availability.country_code IN ({country_marks}) "
                "AND availability.availability_status = 'unsupported')"
            )
            all_supported = (
                "(SELECT COUNT(DISTINCT availability.country_code) "
                "FROM offer_availability availability "
                "WHERE availability.offer_id = offers.offer_id "
                f"AND availability.country_code IN ({country_marks}) "
                "AND availability.availability_status = 'supported') = ?"
            )
            if include_unknown_region:
                clauses.append(f"({no_unsupported})")
                parameters.extend(countries)
            else:
                clauses.append(
                    f"({no_unsupported} AND (availability_scope = 'global' OR {all_supported}))"
                )
                parameters.extend(countries)
                parameters.extend(countries)
                parameters.append(len(countries))
        elif countries:
            # Unknown country availability is represented by no row.  It can
            # only be included on explicit request, never by a default filter.
            country_marks = ",".join("?" for _ in countries)
            if include_unknown_region:
                clauses.append(
                    "(NOT EXISTS ("
                    "SELECT 1 FROM offer_availability availability "
                    "WHERE availability.offer_id = offers.offer_id "
                    f"AND availability.country_code IN ({country_marks}) "
                    "AND availability.availability_status = 'unsupported'))"
                )
            else:
                clauses.append(
                    "(NOT EXISTS (SELECT 1 FROM offer_availability availability "
                    "WHERE availability.offer_id = offers.offer_id "
                    f"AND availability.country_code IN ({country_marks}) "
                    "AND availability.availability_status = 'unsupported') AND ("
                    "EXISTS ("
                    "SELECT 1 FROM offer_availability availability "
                    "WHERE availability.offer_id = offers.offer_id "
                    f"AND availability.country_code IN ({country_marks}) "
                    "AND availability.availability_status = 'supported') "
                    "OR availability_scope = 'global'))"
                )
                parameters.extend(countries)
            parameters.extend(countries)
        if query:
            clauses.append("(provider LIKE ? OR title LIKE ?)")
            token = f"%{query[:100]}%"
            parameters.extend((token, token))
        availability_order = ""
        if countries:
            country_literals = ",".join(f"'{code}'" for code in countries)
            unsupported = (
                "NOT EXISTS (SELECT 1 FROM offer_availability availability "
                "WHERE availability.offer_id = offers.offer_id "
                f"AND availability.country_code IN ({country_literals}) "
                "AND availability.availability_status = 'unsupported')"
            )
            if region_countries:
                supported = (
                    "(SELECT COUNT(DISTINCT availability.country_code) "
                    "FROM offer_availability availability "
                    "WHERE availability.offer_id = offers.offer_id "
                    f"AND availability.country_code IN ({country_literals}) "
                    "AND availability.availability_status = 'supported') = "
                    f"{len(countries)}"
                )
            else:
                supported = (
                    "EXISTS (SELECT 1 FROM offer_availability availability "
                    "WHERE availability.offer_id = offers.offer_id "
                    f"AND availability.country_code IN ({country_literals}) "
                    "AND availability.availability_status = 'supported')"
                )
            availability_order = (
                f"CASE WHEN {supported} THEN 0 "
                f"WHEN availability_scope = 'global' AND {unsupported} THEN 1 "
                "ELSE 2 END,\n                "
            )
        parameters.extend((limit, offset))
        rows = connection.execute(
            f"""
            SELECT * FROM offers
            WHERE {' AND '.join(clauses)}
            ORDER BY
                {availability_order}
                CASE priority_tier
                    WHEN 'A' THEN 0 WHEN 'B' THEN 1
                    WHEN 'C' THEN 2 ELSE 3 END,
                CASE requires_card
                    WHEN 'no' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END,
                COALESCE(estimated_usd_value, -1) DESC,
                last_changed_at DESC,
                provider COLLATE NOCASE,
                title COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            parameters,
        ).fetchall()
        return tuple(
            _offer_dict(
                connection,
                row,
                locale=locale.strip(),
                availability_context=countries,
                strict_region=bool(region_countries),
            )
            for row in rows
        )
    finally:
        connection.close()


SOURCE_FRESHNESS_STATES = (
    "fresh",
    "overdue",
    "stale",
    "verification_pending",
    "failed",
    "never",
)


def _source_time(value: Any, *, current: datetime) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    return parsed.astimezone(current.tzinfo)


def source_freshness_status(
    *,
    last_success_at: str | None,
    cadence_hours: int,
    last_error_code: str | None = None,
    last_result_status: str | None = None,
    now: datetime | None = None,
) -> tuple[str, float | None]:
    """Classify one source using the documented cadence-aware boundaries."""

    current = (now or datetime.now().astimezone()).astimezone()
    success = _source_time(last_success_at, current=current)
    age_hours = (
        max(0.0, (current - success).total_seconds() / 3600)
        if success is not None
        else None
    )
    if last_error_code:
        if last_result_status == "verification_pending":
            return "verification_pending", age_hours
        return "failed", age_hours
    if success is None:
        return "never", None
    assert age_hours is not None
    cadence = max(1, int(cadence_hours))
    if age_hours <= cadence + 6:
        return "fresh", age_hours
    if age_hours <= cadence * 2:
        return "overdue", age_hours
    return "stale", age_hours


def source_statuses(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], ...]:
    current = (now or datetime.now().astimezone()).astimezone()
    rows = connection.execute(
        """
        SELECT s.*,
            (
                SELECT f.status FROM fetch_runs f
                WHERE f.source_id = s.source_id
                  AND f.status IN (
                    'success', 'not_modified', 'verification_pending', 'failed'
                  )
                ORDER BY f.id DESC LIMIT 1
            ) AS last_result_status,
            (
                SELECT f.status FROM fetch_runs f
                WHERE f.source_id = s.source_id
                ORDER BY f.id DESC LIMIT 1
            ) AS latest_run_status,
            (
                SELECT f.started_at FROM fetch_runs f
                WHERE f.source_id = s.source_id
                ORDER BY f.id DESC LIMIT 1
            ) AS latest_run_started_at
        FROM sources s
        ORDER BY CASE s.authority WHEN 'community' THEN 1 ELSE 0 END,
                 s.name COLLATE NOCASE
        """
    ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        latest_run_started_at = _source_time(
            row["latest_run_started_at"], current=current
        )
        abandoned_run = (
            row["latest_run_status"] == "running"
            and latest_run_started_at is not None
            and current - latest_run_started_at
            >= timedelta(minutes=ABANDONED_FETCH_RUN_MINUTES)
        )
        effective_error_code = (
            "fetch_run_abandoned" if abandoned_run else row["last_error_code"]
        )
        effective_result_status = (
            "failed" if abandoned_run else row["last_result_status"]
        )
        status, age_hours = source_freshness_status(
            last_success_at=row["last_success_at"],
            cadence_hours=int(row["cadence_hours"]),
            last_error_code=effective_error_code,
            last_result_status=effective_result_status,
            now=current,
        )
        output.append(
            {
                "source_id": row["source_id"],
                "name": row["name"],
                "authority": row["authority"],
                "cadence_hours": int(row["cadence_hours"]),
                "status": status,
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "last_error_code": effective_error_code,
                "age_hours": round(age_hours, 2) if age_hours is not None else None,
            }
        )
    return tuple(output)


def _empty_source_summary() -> dict[str, Any]:
    counts = {state: 0 for state in SOURCE_FRESHNESS_STATES}
    counts["never"] = len(SOURCES)
    return {
        "total": len(SOURCES),
        "healthy": 0,
        "failed": 0,
        **counts,
        "status_counts": counts,
        "oldest_official_verified_at": None,
        "oldest_official_age_hours": None,
        "items": (),
    }


def radar_summary(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now().astimezone()).astimezone()
    if not path.exists():
        return {
            "schema_version": "2.0",
            "counts": {"active": 0, "tier_a": 0, "new_today": 0, "expiring": 0},
            "sources": _empty_source_summary(),
            "notifications": {"unread": 0},
            "last_refresh_at": None,
            "storage": {
                "database_bytes": 0,
                "retention": {
                    "fetch_runs_days": FETCH_RUN_RETENTION_DAYS,
                    "ordinary_changes_days": CHANGE_RETENTION_DAYS,
                    "delivered_notifications_days": NOTIFICATION_RETENTION_DAYS,
                    "daily_posters_days": POSTER_RETENTION_DAYS,
                    "important_free_changes": "forever",
                },
                "posters": {"count": 0, "bytes": 0},
                "history_rebuilt_at": None,
                "schema_migrated_at": None,
                "last_maintenance_at": None,
                "last_vacuum_at": None,
                "vacuum_pending": False,
            },
        }
    connection = connect(path)
    try:
        today = current.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        expiry = (current + timedelta(days=7)).date().isoformat()
        counts = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status = 'active' AND priority_tier = 'A' THEN 1 ELSE 0 END) AS tier_a,
                SUM(CASE WHEN first_seen_at >= ? THEN 1 ELSE 0 END) AS new_today,
                SUM(CASE WHEN status = 'active' AND expires_at IS NOT NULL
                    AND expires_at <= ? THEN 1 ELSE 0 END) AS expiring
            FROM offers
            """,
            (today, expiry),
        ).fetchone()
        source_row = connection.execute(
            "SELECT MAX(last_attempt_at) AS last_refresh_at FROM sources"
        ).fetchone()
        statuses = source_statuses(connection, now=current)
        status_counts = {
            state: sum(item["status"] == state for item in statuses)
            for state in SOURCE_FRESHNESS_STATES
        }
        official_times = [
            parsed
            for item in statuses
            if item["authority"] != "community"
            for parsed in (
                _source_time(item["last_success_at"], current=current),
            )
            if parsed is not None
        ]
        oldest_official = min(official_times) if official_times else None
        unread = connection.execute(
            "SELECT COUNT(*) FROM notifications WHERE status != 'read'"
        ).fetchone()[0]
        return {
            "schema_version": "2.0",
            "counts": {
                "active": int(counts["active"] or 0),
                "tier_a": int(counts["tier_a"] or 0),
                "new_today": int(counts["new_today"] or 0),
                "expiring": int(counts["expiring"] or 0),
            },
            "sources": {
                "total": len(statuses),
                "healthy": status_counts["fresh"],
                "failed": (
                    status_counts["failed"]
                    + status_counts["verification_pending"]
                ),
                **status_counts,
                "status_counts": status_counts,
                "oldest_official_verified_at": (
                    oldest_official.isoformat(timespec="seconds")
                    if oldest_official
                    else None
                ),
                "oldest_official_age_hours": (
                    round(
                        max(
                            0.0,
                            (current - oldest_official).total_seconds() / 3600,
                        ),
                        2,
                    )
                    if oldest_official
                    else None
                ),
                "items": statuses,
            },
            "notifications": {"unread": int(unread)},
            "last_refresh_at": source_row["last_refresh_at"],
            "storage": storage_summary(connection),
        }
    finally:
        connection.close()


def list_changes(
    path: Path, *, days: int = 30, limit: int = 100
) -> tuple[dict[str, Any], ...]:
    if not 1 <= days <= 365 or not 1 <= limit <= 500:
        raise ValueError("invalid_change_filter")
    if not path.exists():
        return ()
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT c.id, c.offer_id, c.detected_at, c.change_type,
                   c.changed_fields_json, c.importance,
                   o.provider, o.title, o.kind, o.offer_type,
                   o.priority_tier, o.verification_level, o.expires_at,
                   o.homepage_url, o.status
            FROM offer_changes c
            LEFT JOIN offers o ON o.offer_id = c.offer_id
            WHERE c.detected_at >= ?
            ORDER BY c.detected_at DESC, c.id DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
        return tuple(
            {
                **dict(row),
                "changed_fields": json.loads(row["changed_fields_json"]),
            }
            for row in rows
        )
    finally:
        connection.close()


def pending_notifications(
    path: Path, *, limit: int = 5
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= 20 or not path.exists():
        return ()
    connection = connect(path)
    try:
        rows = connection.execute(
            """
            SELECT id, created_at, title, body, target_url, item_count, status
            FROM notifications
            WHERE status = 'pending'
            ORDER BY created_at ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(dict(row) for row in rows)
    finally:
        connection.close()


def mark_notification(path: Path, notification_id: int, *, status: str) -> bool:
    if status not in {"delivered", "read"} or not path.exists():
        return False
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    connection = connect(path)
    try:
        with connection:
            if status == "delivered":
                cursor = connection.execute(
                    """
                    UPDATE notifications
                    SET status = CASE WHEN status = 'read' THEN 'read' ELSE 'delivered' END,
                        delivered_at = COALESCE(delivered_at, ?)
                    WHERE id = ?
                    """,
                    (now, notification_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE notifications
                    SET status = 'read', read_at = ?,
                        delivered_at = COALESCE(delivered_at, ?)
                    WHERE id = ?
                    """,
                    (now, now, notification_id),
                )
        return cursor.rowcount == 1
    finally:
        connection.close()

__all__ = ["SOURCE_FRESHNESS_STATES", "begin_run", "classify_offer", "connect", "enqueue_digest", "finish_failure", "finish_not_modified", "finish_skipped", "ingest_source", "list_changes", "list_offers", "mark_notification", "pending_notifications", "radar_summary", "source_cache", "source_freshness_status", "source_is_due", "source_statuses"]
