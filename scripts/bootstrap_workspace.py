#!/usr/bin/env python3
"""Operator-only first-workspace bootstrap. Not a public HTTP endpoint.

Prints the plaintext workspace API key once. Do not paste that value into
GitHub, logs, tickets, screenshots, or committed files.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.database import SessionLocal, get_database_url
from app.models import ApiKey, Tenant, Workspace
from app.runtime_validation import validate_runtime_config


SLUG_RE = re.compile(r"[^a-z0-9]+")


class BootstrapError(Exception):
    """Fail-closed bootstrap failure. Never include API key material."""


@dataclass(frozen=True)
class BootstrapResult:
    tenant_id: str
    workspace_id: str
    key_id: str
    key_prefix: str
    api_key: str


def workspace_slug(workspace_name: str) -> str:
    slug = SLUG_RE.sub("-", workspace_name.strip().lower()).strip("-")
    if not slug:
        raise BootstrapError("Workspace name does not produce a usable slug")
    return slug


def _require_database_url() -> str:
    try:
        database_url = get_database_url()
    except RuntimeError as exc:
        raise BootstrapError(str(exc)) from exc
    if any(marker.lower() in database_url.lower() for marker in ("REPLACE", "change-me")):
        raise BootstrapError("DATABASE_URL still contains a placeholder value")
    return database_url


def validate_bootstrap_runtime() -> None:
    _require_database_url()
    if os.getenv("APP_ENV", "").strip().lower() == "production":
        try:
            validate_runtime_config()
        except RuntimeError as exc:
            raise BootstrapError(str(exc)) from exc


def create_workspace(
    db: Session,
    *,
    tenant_name: str,
    workspace_name: str,
) -> BootstrapResult:
    tenant_name = tenant_name.strip()
    workspace_name = workspace_name.strip()
    if not tenant_name or not workspace_name:
        raise BootstrapError("Tenant name and workspace name are required")

    slug = workspace_slug(workspace_name)
    if db.query(Tenant).filter(Tenant.name == tenant_name).first() is not None:
        raise BootstrapError("Tenant name already exists; refusing ambiguous bootstrap")
    if (
        db.query(Workspace)
        .filter((Workspace.slug == slug) | (Workspace.name == workspace_name))
        .first()
        is not None
    ):
        raise BootstrapError("Workspace name or slug already exists; refusing ambiguous bootstrap")

    tenant = Tenant(name=tenant_name, plan="free", status="active")
    workspace = Workspace(name=workspace_name, slug=slug, tenant=tenant)
    plaintext = f"mbs_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    api_key = ApiKey(
        name="Bootstrap",
        key_prefix=plaintext[:12],
        key_hash=key_hash,
        is_active=True,
        workspace=workspace,
    )
    db.add(tenant)
    db.flush()
    db.commit()
    db.refresh(tenant)
    db.refresh(workspace)
    db.refresh(api_key)
    return BootstrapResult(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        key_id=api_key.id,
        key_prefix=api_key.key_prefix,
        api_key=plaintext,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the first MemoryBridge tenant, workspace, and API key. Operator-only.",
    )
    parser.add_argument("--tenant-name", required=True, help="Exact tenant display name")
    parser.add_argument("--workspace-name", required=True, help="Exact workspace display name")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        validate_bootstrap_runtime()
        db = SessionLocal()
        try:
            result = create_workspace(
                db,
                tenant_name=args.tenant_name,
                workspace_name=args.workspace_name,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except BootstrapError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except SystemExit:
        raise
    except Exception as exc:
        print(f"FAIL: bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(f"tenant_id={result.tenant_id}")
    print(f"workspace_id={result.workspace_id}")
    print(f"key_prefix={result.key_prefix}")
    print("WARNING: The following workspace API key is shown once.")
    print("WARNING: Do not paste it into GitHub, logs, tickets, screenshots, or committed files.")
    print(result.api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
