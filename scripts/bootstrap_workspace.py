#!/usr/bin/env python3
"""Operator-only first-workspace bootstrap. Not a public HTTP endpoint.

Prints the plaintext workspace API key once after a successful database commit.
Do not paste that value into GitHub, logs, tickets, screenshots, or committed files.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    from app.database import get_database_url

    try:
        database_url = get_database_url()
    except RuntimeError as exc:
        raise BootstrapError(str(exc)) from exc
    if any(marker.lower() in database_url.lower() for marker in ("REPLACE", "change-me")):
        raise BootstrapError("DATABASE_URL still contains a placeholder value")
    return database_url


def validate_bootstrap_runtime() -> None:
    _require_database_url()


def create_workspace(
    db,
    *,
    tenant_name: str,
    workspace_name: str,
) -> BootstrapResult:
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

    from app.models import ApiKey, Tenant, Workspace

    tenant_name = tenant_name.strip()
    workspace_name = workspace_name.strip()
    if not tenant_name or not workspace_name:
        raise BootstrapError("Tenant name and workspace name are required")

    slug = workspace_slug(workspace_name)
    try:
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
    except BootstrapError:
        db.rollback()
        raise
    except (OperationalError, ProgrammingError) as exc:
        db.rollback()
        raise BootstrapError(
            "Database schema is missing or incomplete. Run `alembic upgrade head` before bootstrap."
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise BootstrapError("Bootstrap collided with an existing tenant or workspace") from exc
    except Exception:
        db.rollback()
        raise

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


def open_session():
    from app.database import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        validate_bootstrap_runtime()
        db = open_session()
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
    except Exception:
        print("FAIL: bootstrap failed", file=sys.stderr)
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
