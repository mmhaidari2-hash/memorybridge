"""Idempotent schema repair for drifted Railway/Postgres databases.

Some environments have a partial ``tenants`` table (no ``slug``) while Alembic
is stamped ahead or stuck — ``alembic upgrade`` alone cannot fix that.
This script adds missing foundation columns/tables safely, then Alembic can
continue from the recorded revision.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import create_engine, inspect, text

from app.database import get_database_url

logger = logging.getLogger("memorybridge.schema_repair")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def _cols(insp, table: str) -> set[str]:
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def repair() -> None:
    url = get_database_url()
    engine = create_engine(url)
    with engine.begin() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())

        if "tenants" not in tables:
            logger.info("tenants missing — leaving creation to Alembic 0002")
            return

        tenant_cols = _cols(insp, "tenants")
        if "slug" not in tenant_cols:
            logger.warning("repairing tenants.slug (was missing)")
            conn.execute(text("ALTER TABLE tenants ADD COLUMN slug VARCHAR(100)"))
            conn.execute(
                text(
                    "UPDATE tenants SET slug = 'default-' || substr(id, 1, 8) "
                    "WHERE slug IS NULL OR slug = ''"
                )
            )
            # Prefer a single canonical default row when present.
            conn.execute(
                text(
                    f"UPDATE tenants SET slug = 'default' "
                    f"WHERE id = '{DEFAULT_TENANT_ID}'"
                )
            )
            conn.execute(text("ALTER TABLE tenants ALTER COLUMN slug SET NOT NULL"))
            # Unique index — ignore if already present.
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)"
                )
            )

        tenant_cols = _cols(inspect(conn), "tenants")
        if "status" not in tenant_cols:
            logger.warning("repairing tenants.status")
            conn.execute(
                text(
                    "ALTER TABLE tenants ADD COLUMN status VARCHAR(32) "
                    "NOT NULL DEFAULT 'active'"
                )
            )
        if "name" not in tenant_cols:
            logger.warning("repairing tenants.name")
            conn.execute(
                text(
                    "ALTER TABLE tenants ADD COLUMN name VARCHAR(200) "
                    "NOT NULL DEFAULT 'Tenant'"
                )
            )
        if "created_at" not in tenant_cols:
            logger.warning("repairing tenants.created_at")
            conn.execute(
                text(
                    "ALTER TABLE tenants ADD COLUMN created_at TIMESTAMP "
                    "NOT NULL DEFAULT CURRENT_TIMESTAMP"
                )
            )
        if "deleted_at" not in tenant_cols:
            logger.warning("repairing tenants.deleted_at")
            conn.execute(text("ALTER TABLE tenants ADD COLUMN deleted_at TIMESTAMP"))

    logger.info("schema_repair_complete")


if __name__ == "__main__":
    try:
        repair()
    except Exception:
        logger.exception("schema_repair_failed")
        sys.exit(1)
