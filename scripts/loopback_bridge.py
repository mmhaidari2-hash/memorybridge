#!/usr/bin/env python3
"""Loopback CLI for MemoryBridge manual records.

Moves the same JSON/SQL contract as IndexedDB between a local SQLite file
and, optionally, an HTTP server bound only to loopback. It never proxies
/v1, never stores workspace API keys, and cannot grant paid entitlement.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.manual_records import (
    BUNDLE_KIND,
    BUNDLE_VERSION,
    ManualRecordError,
    export_bundle,
    export_json,
    export_sqlite_sql,
    import_bundle,
    import_sqlite_sql,
    normalize_record,
)


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORT = 8765
DEFAULT_DB = Path("memorybridge-local-records.sqlite")


class LoopbackBridgeError(ValueError):
    pass


def assert_loopback_host(host: str) -> str:
    cleaned = (host or "").strip().strip("[]")
    if cleaned not in LOOPBACK_HOSTS:
        raise LoopbackBridgeError("Loopback bridge refuses to bind off 127.0.0.1 / localhost / ::1")
    return host.strip()


def is_loopback_origin(origin: str) -> bool:
    if not origin:
        return False
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip("[]")
    return host in LOOPBACK_HOSTS


def is_loopback_peer(addr: str) -> bool:
    return addr in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


class RecordStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_records (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  title TEXT NOT NULL,
                  body TEXT NOT NULL,
                  source TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_records(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, title, body, source FROM manual_records ORDER BY created_at DESC"
            ).fetchall()
        return [normalize_record(dict(row)) for row in rows]

    def upsert(self, raw: dict[str, Any]) -> dict[str, str]:
        record = normalize_record(raw)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO manual_records (id, created_at, title, body, source)
                VALUES (:id, :created_at, :title, :body, :source)
                ON CONFLICT(id) DO UPDATE SET
                  created_at=excluded.created_at,
                  title=excluded.title,
                  body=excluded.body,
                  source=excluded.source
                """,
                record,
            )
            conn.commit()
        return record

    def import_records(self, records: list[dict[str, Any]]) -> list[dict[str, str]]:
        stored = [self.upsert(item) for item in records]
        return stored


def parse_import_text(text: str) -> list[dict[str, str]]:
    trimmed = text.strip()
    if not trimmed:
        raise ManualRecordError("Import payload is empty")
    if trimmed.startswith("{"):
        return import_bundle(trimmed)
    return import_sqlite_sql(trimmed)


class LoopbackHandler(BaseHTTPRequestHandler):
    server_version = "MemoryBridgeLoopback/0.4"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _store(self) -> RecordStore:
        return self.server.store  # type: ignore[attr-defined]

    def _send(self, status: int, payload: dict[str, Any], origin: str | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if origin and is_loopback_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_if_not_loopback(self) -> bool:
        peer = self.client_address[0]
        if not is_loopback_peer(peer):
            self._send(403, {"ok": False, "error": "Loopback peers only"})
            return True
        return False

    def do_OPTIONS(self) -> None:
        if self._reject_if_not_loopback():
            return
        origin = self.headers.get("Origin", "")
        if origin and not is_loopback_origin(origin):
            self._send(403, {"ok": False, "error": "Loopback origins only"})
            return
        self.send_response(204)
        if origin and is_loopback_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self._reject_if_not_loopback():
            return
        origin = self.headers.get("Origin", "")
        if origin and not is_loopback_origin(origin):
            self._send(403, {"ok": False, "error": "Loopback origins only"}, None)
            return
        path = urlparse(self.path).path
        try:
            if path == "/health":
                self._send(
                    200,
                    {
                        "ok": True,
                        "kind": BUNDLE_KIND,
                        "version": BUNDLE_VERSION,
                        "count": len(self._store().list_records()),
                    },
                    origin,
                )
                return
            if path == "/records":
                self._send(200, export_bundle(self._store().list_records()), origin)
                return
        except ManualRecordError as exc:
            self._send(400, {"ok": False, "error": str(exc)}, origin)
            return
        self._send(404, {"ok": False, "error": "Not found"}, origin)

    def do_POST(self) -> None:
        if self._reject_if_not_loopback():
            return
        origin = self.headers.get("Origin", "")
        if origin and not is_loopback_origin(origin):
            self._send(403, {"ok": False, "error": "Loopback origins only"}, None)
            return
        if urlparse(self.path).path != "/records":
            self._send(404, {"ok": False, "error": "Not found"}, origin)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            self._send(400, {"ok": False, "error": "Import payload is empty or too large"}, origin)
            return
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("kind") == BUNDLE_KIND:
                records = import_bundle(payload)
            elif isinstance(payload, dict):
                source = str(payload.get("source") or "cli")
                records = [normalize_record({**payload, "source": source})]
            else:
                raise ManualRecordError("Import payload must be an object")
            stored = self._store().import_records(records)
        except (json.JSONDecodeError, ManualRecordError) as exc:
            self._send(400, {"ok": False, "error": str(exc)}, origin)
            return
        self._send(200, {"ok": True, "imported": len(stored)}, origin)


def serve(host: str, port: int, store: RecordStore) -> ThreadingHTTPServer:
    bound = assert_loopback_host(host)
    server = ThreadingHTTPServer((bound, port), LoopbackHandler)
    server.store = store  # type: ignore[attr-defined]
    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local loopback CLI for MemoryBridge manual records. Does not grant paid entitlement.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite file for local drafts")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Append one local draft")
    record.add_argument("--title", required=True)
    record.add_argument("--body", required=True)
    record.add_argument("--source", default="cli")

    sub.add_parser("list", help="List local draft titles")

    export_cmd = sub.add_parser("export", help="Write JSON or SQLite SQL")
    export_fmt = export_cmd.add_mutually_exclusive_group(required=True)
    export_fmt.add_argument("--json", type=Path)
    export_fmt.add_argument("--sql", type=Path)

    import_cmd = sub.add_parser("import", help="Import JSON or SQLite SQL")
    import_cmd.add_argument("path", type=Path)

    serve_cmd = sub.add_parser("serve", help="Serve the same store on loopback HTTP")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        store = RecordStore(args.db)
        if args.command == "record":
            record = store.upsert({"title": args.title, "body": args.body, "source": args.source})
            print(f"id={record['id']}")
            print(f"source={record['source']}")
            return 0
        if args.command == "list":
            records = store.list_records()
            print(f"count={len(records)}")
            for item in records:
                print(f"{item['id']}\t{item['source']}\t{item['title']}")
            return 0
        if args.command == "export":
            records = store.list_records()
            if args.json:
                args.json.write_text(export_json(records), encoding="utf-8")
                print(f"wrote={args.json}")
            else:
                args.sql.write_text(export_sqlite_sql(records), encoding="utf-8")
                print(f"wrote={args.sql}")
            return 0
        if args.command == "import":
            imported = store.import_records(parse_import_text(args.path.read_text(encoding="utf-8")))
            print(f"imported={len(imported)}")
            return 0
        if args.command == "serve":
            server = serve(args.host, args.port, store)
            host, port = server.server_address[:2]
            print(f"loopback={host}:{port}")
            print("kind=memorybridge.manual_records")
            print("WARNING: This server is local drafts only. It does not grant paid entitlement.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
            finally:
                server.server_close()
            return 0
    except (LoopbackBridgeError, ManualRecordError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
