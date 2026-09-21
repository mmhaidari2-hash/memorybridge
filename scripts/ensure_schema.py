"""Idempotent schema repair + Alembic stamp for drifted Railway DBs."""

from __future__ import annotations

import logging
import sys

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.database import get_database_url

logger = logging.getLogger("memorybridge.schema_repair")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def _cols(insp, table: str) -> set[str]:
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _current_revision(conn) -> str | None:
    context = MigrationContext.configure(conn)
    return context.get_current_revision()


def _stamp(conn, revision: str) -> None:
    # Prefer raw insert/update so we don't require a full Alembic env transaction dance.
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
    )
    existing = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    if existing:
        conn.execute(
            text("UPDATE alembic_version SET version_num = :rev"),
            {"rev": revision},
        )
    else:
        conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
            {"rev": revision},
        )
    logger.warning("stamped alembic_version=%s", revision)


def repair() -> None:
    url = get_database_url()
    engine = create_engine(url)
    with engine.begin() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())

        if "tenants" in tables:
            tenant_cols = _cols(insp, "tenants")
            if "slug" not in tenant_cols:
                logger.warning("repairing tenants.slug")
                conn.execute(text("ALTER TABLE tenants ADD COLUMN slug VARCHAR(100)"))
                conn.execute(
                    text(
                        "UPDATE tenants SET slug = 'default-' || substr(id::text, 1, 8) "
                        "WHERE slug IS NULL OR slug = ''"
                    )
                )
                conn.execute(
                    text(
                        f"UPDATE tenants SET slug = 'default' "
                        f"WHERE id = '{DEFAULT_TENANT_ID}'"
                    )
                )
                conn.execute(text("ALTER TABLE tenants ALTER COLUMN slug SET NOT NULL"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)"
                    )
                )
            insp = inspect(conn)
            tenant_cols = _cols(insp, "tenants")
            if "status" not in tenant_cols:
                conn.execute(
                    text(
                        "ALTER TABLE tenants ADD COLUMN status VARCHAR(32) "
                        "NOT NULL DEFAULT 'active'"
                    )
                )
            if "name" not in tenant_cols:
                conn.execute(
                    text(
                        "ALTER TABLE tenants ADD COLUMN name VARCHAR(200) "
                        "NOT NULL DEFAULT 'Tenant'"
                    )
                )
            if "created_at" not in tenant_cols:
                conn.execute(
                    text(
                        "ALTER TABLE tenants ADD COLUMN created_at TIMESTAMP "
                        "NOT NULL DEFAULT CURRENT_TIMESTAMP"
                    )
                )
            if "deleted_at" not in tenant_cols:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN deleted_at TIMESTAMP NULL"))

        # If commercial foundation tables exist but Alembic is behind/empty, stamp 0002
        # so later revisions (plans, billing, webhooks) can apply cleanly.
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        tenant_cols = _cols(insp, "tenants")
        has_foundation = (
            "tenants" in tables
            and "slug" in tenant_cols
            and "service_api_keys" in tables
        )
        rev = _current_revision(conn)
        logger.info("alembic_current_revision=%s", rev)
        if has_foundation and rev in (None, "0001_secure_foundation"):
            _stamp(conn, "0002_commercial_foundation")

    logger.info("schema_repair_complete")


if __name__ == "__main__":
    try:
        repair()
    except Exception:
        logger.exception("schema_repair_failed")
        sys.exit(1)
