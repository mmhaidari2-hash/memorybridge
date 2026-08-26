#!/usr/bin/env python3
"""MemoryBridge deployment smoke checks.

Usage:
  python scripts/deployment_smoke.py https://api.example.com
  MEMORYBRIDGE_API_KEY=mbs_... python scripts/deployment_smoke.py https://api.example.com

The script never prints the API key.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


USAGE = "Usage: python scripts/deployment_smoke.py https://api.example.com"


def request(url: str, method: str = "GET", headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, dict(exc.headers), body


def expect_json(url: str, expected_status: int, expected_status_value: str):
    status, headers, body = request(url)
    if status != expected_status:
        raise RuntimeError(f"{url} returned HTTP {status}, expected {expected_status}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} did not return JSON") from exc
    if payload.get("status") != expected_status_value:
        raise RuntimeError(f"{url} returned unexpected status payload: {payload!r}")
    request_id = headers.get("X-Request-ID") or headers.get("x-request-id")
    return payload, request_id


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        print(USAGE)
        print("Optional: set MEMORYBRIDGE_API_KEY to verify /v1/account/status.")
        return 0

    if len(sys.argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2

    base = sys.argv[1].rstrip("/")
    if not base.startswith("https://"):
        print("Refusing non-HTTPS deployment target.", file=sys.stderr)
        return 2

    print("[1/4] health")
    expect_json(f"{base}/health", 200, "ok")

    print("[2/4] readiness")
    expect_json(f"{base}/ready", 200, "ready")

    print("[3/4] root metadata")
    status, _, body = request(f"{base}/")
    if status != 200:
        raise RuntimeError(f"root returned HTTP {status}")
    root = json.loads(body)
    if root.get("service") != "memorybridge":
        raise RuntimeError(f"unexpected root payload: {root!r}")

    print("[4/4] authenticated account path (optional)")
    key = os.getenv("MEMORYBRIDGE_API_KEY", "").strip()
    if key:
        status, _, body = request(
            f"{base}/v1/account/status",
            headers={"X-MemoryBridge-Key": key},
        )
        if status != 200:
            raise RuntimeError(f"account/status returned HTTP {status}: {body[:200]}")
        account = json.loads(body)
        required = {"workspace_id", "plan", "usage_used", "usage_limit", "can_upgrade"}
        missing = sorted(required.difference(account))
        if missing:
            raise RuntimeError(f"account/status missing fields: {', '.join(missing)}")
        print(f"      workspace={account.get('workspace_name', '<unnamed>')} plan={account.get('plan')}")
    else:
        print("      skipped: set MEMORYBRIDGE_API_KEY to verify the customer control plane")

    print("PASS: deployment smoke checks completed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
