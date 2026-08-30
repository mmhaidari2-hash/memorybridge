"""Canonical format for local manual records.

Browser IndexedDB is the runtime store. Export/import uses JSON and a
SQLite-compatible SQL dump. This module is the tested format contract.
It never accepts API keys, Stripe secrets, or memory-session tokens.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any


BUNDLE_KIND = "memorybridge.manual_records"
BUNDLE_VERSION = 1
SECRET_MARKERS = (
    "mbs_",
    "sk_live_",
    "sk_test_",
    "whsec_",
    "STRIPE_SECRET",
    "STRIPE_WEBHOOK",
)
ALLOWED_SOURCES = {"manual", "extension", "cli"}
_INSERT_PREFIX = "INSERT INTO manual_records (id, created_at, title, body, source) VALUES ("


class ManualRecordError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _looks_secret(value: str) -> bool:
    lowered = value.lower()
    return any(marker.lower() in lowered for marker in SECRET_MARKERS)


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _sql_unescape(value: str) -> str:
    return value.replace("''", "'")


def normalize_record(raw: dict[str, Any]) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ManualRecordError("Record must be an object")
    title = str(raw.get("title") or "").strip()
    body = str(raw.get("body") or "").strip()
    source = str(raw.get("source") or "manual").strip() or "manual"
    record_id = str(raw.get("id") or uuid.uuid4()).strip()
    created_at = str(raw.get("created_at") or _now()).strip()
    if not title or not body:
        raise ManualRecordError("Record title and body are required")
    if source not in ALLOWED_SOURCES:
        raise ManualRecordError("Record source is not allowed")
    for field in (title, body, record_id, created_at, source):
        if _looks_secret(field):
            raise ManualRecordError("Manual records cannot contain credentials")
    return {
        "id": record_id,
        "created_at": created_at,
        "title": title,
        "body": body,
        "source": source,
    }


def export_bundle(records: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [normalize_record(item) for item in records]
    return {"version": BUNDLE_VERSION, "kind": BUNDLE_KIND, "records": normalized}


def export_json(records: list[dict[str, Any]]) -> str:
    return json.dumps(export_bundle(records), ensure_ascii=True, indent=2)


def export_sqlite_sql(records: list[dict[str, Any]]) -> str:
    lines = [
        "BEGIN TRANSACTION;",
        "CREATE TABLE IF NOT EXISTS manual_records (",
        "  id TEXT PRIMARY KEY,",
        "  created_at TEXT NOT NULL,",
        "  title TEXT NOT NULL,",
        "  body TEXT NOT NULL,",
        "  source TEXT NOT NULL",
        ");",
    ]
    for item in export_bundle(records)["records"]:
        lines.append(
            "INSERT INTO manual_records (id, created_at, title, body, source) VALUES ("
            f"'{_sql_escape(item['id'])}', "
            f"'{_sql_escape(item['created_at'])}', "
            f"'{_sql_escape(item['title'])}', "
            f"'{_sql_escape(item['body'])}', "
            f"'{_sql_escape(item['source'])}'"
            ");"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def import_bundle(payload: Any) -> list[dict[str, str]]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ManualRecordError("Import JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise ManualRecordError("Import bundle must be an object")
    if payload.get("kind") != BUNDLE_KIND:
        raise ManualRecordError("Import bundle kind is not recognized")
    if int(payload.get("version") or 0) != BUNDLE_VERSION:
        raise ManualRecordError("Import bundle version is not supported")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ManualRecordError("Import bundle records must be a list")
    return [normalize_record(item) for item in records]


def _parse_sql_string_values(blob: str) -> list[str]:
    values: list[str] = []
    index = 0
    length = len(blob)
    while index < length:
        if blob[index] in " \t,":
            index += 1
            continue
        if blob[index] != "'":
            raise ManualRecordError("SQLite import values must be quoted")
        index += 1
        chars: list[str] = []
        while index < length:
            if blob[index] == "'" and index + 1 < length and blob[index + 1] == "'":
                chars.append("'")
                index += 2
                continue
            if blob[index] == "'":
                index += 1
                break
            chars.append(blob[index])
            index += 1
        values.append("".join(chars))
    return values


def import_sqlite_sql(sql: str) -> list[dict[str, str]]:
    if _looks_secret(sql):
        raise ManualRecordError("Manual records cannot contain credentials")
    records: list[dict[str, str]] = []
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        upper = line.upper()
        if upper in {"BEGIN TRANSACTION;", "COMMIT;"} or upper.startswith("CREATE TABLE") or line in {");", ")"} or line.endswith(",") and "TEXT" in upper:
            continue
        if not upper.startswith("INSERT "):
            continue
        if not line.lower().startswith(_INSERT_PREFIX.lower()) or not line.endswith(");"):
            raise ManualRecordError("SQLite import only accepts manual_records inserts")
        values = _parse_sql_string_values(line[len(_INSERT_PREFIX) : -2])
        if len(values) != 5:
            raise ManualRecordError("SQLite import row is malformed")
        records.append(
            normalize_record(
                {
                    "id": values[0],
                    "created_at": values[1],
                    "title": values[2],
                    "body": values[3],
                    "source": values[4],
                }
            )
        )
    if not records:
        raise ManualRecordError("SQLite import contained no manual records")
    return records
