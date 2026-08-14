"""Low-level schema migration helpers shared by persistence components."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ai_resource_radar.collection.models import default_presentations
from ai_resource_radar.sources import resolve_modalities

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
def _metadata_get(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute(
        "SELECT value FROM radar_metadata WHERE key = ?", (key,)
    ).fetchone()
    return str(row[0]) if row else None


def _metadata_set(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO radar_metadata(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _database_bytes(connection: sqlite3.Connection) -> int:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    return page_size * page_count


def _decode_json_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _backfill_modality_fields(connection: sqlite3.Connection) -> None:
    """Populate schema-v5 modality columns without misclassifying vision.

    The canonical fingerprint is recalculated so that the next successful
    refresh does not report a synthetic update caused only by the migration.
    """

    required = {
        "input_modalities_json",
        "output_modalities_json",
        "free_image_generation",
    }
    if not required <= _columns(connection, "offers"):
        return
    rows = connection.execute("SELECT * FROM offers").fetchall()
    for row in rows:
        try:
            details = json.loads(row["details_json"] or "{}")
        except (TypeError, ValueError):
            details = {}
        if not isinstance(details, dict):
            details = {}
        inputs, outputs = resolve_modalities(details)
        inputs = inputs or _decode_json_list(row["input_modalities_json"])
        outputs = outputs or _decode_json_list(row["output_modalities_json"])
        free_image = (
            str(row["kind"]) == "token"
            and str(row["offer_type"]) in {"recurring_free", "variable_free"}
            and "image" in outputs
        )
        try:
            reasons = json.loads(row["priority_reasons_json"] or "[]")
        except (TypeError, ValueError):
            reasons = []
        payload = {
            "offer_id": row["offer_id"],
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
            "eligibility": row["eligibility"],
            "mainland_status": row["mainland_status"],
            "expires_at": row["expires_at"],
            "homepage_url": row["homepage_url"],
            "verification_level": row["verification_level"],
            "priority_tier": row["priority_tier"],
            "priority_reasons": reasons,
            "details": details,
            "input_modalities": list(inputs),
            "output_modalities": list(outputs),
            "free_image_generation": free_image,
        }
        fingerprint = hashlib.sha256(_json(payload).encode()).hexdigest()
        connection.execute(
            """
            UPDATE offers SET input_modalities_json = ?,
                output_modalities_json = ?, free_image_generation = ?,
                fingerprint = ? WHERE offer_id = ?
            """,
            (
                _json(list(inputs)),
                _json(list(outputs)),
                int(free_image),
                fingerprint,
                row["offer_id"],
            ),
        )


def _backfill_v8_fields(connection: sqlite3.Connection) -> None:
    """Backfill v0.9 region data without creating a refresh-side effect.

    Schema v7 recorded exactly one availability assertion: ``mainland_status``.
    It is conservative and lossless to store that assertion under ISO2 ``CN``;
    no claim is made for a country which had no previous evidence.  This helper
    is called only by the transactional schema initializer and intentionally
    never touches ``offer_changes`` or ``notifications``.
    """

    required = {
        "requires_identity_verification",
        "requires_paid_topup",
        "requires_waitlist",
        "requires_organization",
        "availability_scope",
    }
    if not required <= _columns(connection, "offers"):
        return
    rows = connection.execute("SELECT * FROM offers").fetchall()
    for row in rows:
        mainland = str(row["mainland_status"] or "unknown")
        if mainland not in {"supported", "unknown", "unsupported"}:
            mainland = "unknown"
        connection.execute(
            """
            UPDATE offers SET requires_identity_verification =
                    COALESCE(NULLIF(requires_identity_verification, ''), 'unknown'),
                requires_paid_topup = COALESCE(NULLIF(requires_paid_topup, ''), 'unknown'),
                requires_waitlist = COALESCE(NULLIF(requires_waitlist, ''), 'unknown'),
                requires_organization = COALESCE(NULLIF(requires_organization, ''), 'unknown'),
                availability_scope = CASE
                    WHEN ? IN ('supported', 'unsupported') THEN 'restricted'
                    ELSE 'unknown' END
            WHERE offer_id = ?
            """,
            (mainland, row["offer_id"]),
        )
        scope = "restricted" if mainland in {"supported", "unsupported"} else "unknown"
        if mainland == "unknown":
            availability: dict[str, str] = {}
        else:
            connection.execute(
                """
                INSERT INTO offer_availability(
                    offer_id, country_code, availability_status, source_url,
                    evidence_excerpt, observed_at
                )
                VALUES (?, 'CN', ?, ?, ?, ?)
                ON CONFLICT(offer_id, country_code) DO NOTHING
                """,
                (
                    row["offer_id"],
                    mainland,
                    row["homepage_url"],
                    "Migrated from schema-v7 mainland_status.",
                    row["last_seen_at"],
                ),
            )
            availability = {"CN": mainland}
        presentations = default_presentations(
            provider=str(row["provider"]),
            title=str(row["title"]),
            eligibility=row["eligibility"],
        )
        for locale, presentation in presentations.items():
            connection.execute(
                """
                INSERT INTO offer_presentations(
                    offer_id, presentation, locale, title, benefit_summary,
                    eligibility, usage_steps_json, limitations_json
                ) VALUES (?, 'default', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(offer_id, presentation, locale) DO NOTHING
                """,
                (
                    row["offer_id"],
                    locale,
                    presentation.get("title"),
                    presentation.get("benefit_summary"),
                    presentation.get("eligibility"),
                    _json(presentation.get("usage_steps") or ()),
                    _json(presentation.get("limitations") or ()),
                ),
            )
        try:
            reasons = json.loads(row["priority_reasons_json"] or "[]")
        except (TypeError, ValueError):
            reasons = []
        try:
            details = json.loads(row["details_json"] or "{}")
        except (TypeError, ValueError):
            details = {}
        payload = {
            "offer_id": row["offer_id"], "provider": row["provider"],
            "title": row["title"], "kind": row["kind"],
            "offer_type": row["offer_type"], "quota_value": row["quota_value"],
            "quota_unit": row["quota_unit"], "reset_period": row["reset_period"],
            "estimated_usd_value": row["estimated_usd_value"],
            "requires_card": row["requires_card"], "requires_phone": row["requires_phone"],
            "requires_identity_verification": "unknown", "requires_paid_topup": "unknown",
            "requires_waitlist": "unknown", "requires_organization": "unknown",
            "signup_requirements": {
                "card": {"yes": "required", "no": "not_required"}.get(row["requires_card"], "unknown"),
                "phone": {"yes": "required", "no": "not_required"}.get(row["requires_phone"], "unknown"),
                "identity_verification": "unknown", "paid_topup": "unknown",
                "waitlist": "unknown", "organization": "unknown",
            },
            "eligibility": row["eligibility"], "mainland_status": mainland,
            "availability_scope": scope, "availability": availability,
            "expires_at": row["expires_at"], "homepage_url": row["homepage_url"],
            "verification_level": row["verification_level"],
            "priority_tier": row["priority_tier"], "priority_reasons": reasons,
            "details": details,
            "input_modalities": list(_decode_json_list(row["input_modalities_json"])),
            "output_modalities": list(_decode_json_list(row["output_modalities_json"])),
            "free_image_generation": bool(row["free_image_generation"]),
        }
        connection.execute(
            "UPDATE offers SET fingerprint = ? WHERE offer_id = ?",
            (hashlib.sha256(_json(payload).encode()).hexdigest(), row["offer_id"]),
        )



__all__ = ["_backfill_modality_fields", "_backfill_v8_fields"]
