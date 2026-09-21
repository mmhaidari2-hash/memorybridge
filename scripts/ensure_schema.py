"""Bring drifted Railway/Postgres schemas up to the current models.

Uses SQLAlchemy ``create_all`` (creates *missing* tables only) plus small
column repairs, then stamps Alembic to head so future revisions stay aligned.
This avoids fragile mid-chain ``alembic upgrade`` on partially-applied DBs.
"""

from __future__ import annotations

import logging
import sys

from alembic.script import ScriptDirectory
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.database import Base, get_database_url
from app import models  # noqa: F401 — register all mappers on Base.metadata

logger = logging.getLogger("memorybridge.schema_repair")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def _cols(insp, table: str) -> set[str]:
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _head_revision() -> str:
    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


def _stamp(conn, revision: str) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
    )
    row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    if row:
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


def _repair_tenants(conn) -> None:
    insp = inspect(conn)
    if "tenants" not in insp.get_table_names():
        return
    cols = _cols(insp, "tenants")
    if "slug" not in cols:
        logger.warning("repairing tenants.slug")
        conn.execute(text("ALTER TABLE tenants ADD COLUMN slug VARCHAR(100)"))
        conn.execute(
            text(
                "UPDATE tenants SET slug = 'tenant-' || substr(replace(id::text, '-', ''), 1, 8) "
                "WHERE slug IS NULL OR btrim(slug) = ''"
            )
        )
        conn.execute(
            text(
                f"UPDATE tenants SET slug = 'default' WHERE id = '{DEFAULT_TENANT_ID}'"
            )
        )
        conn.execute(text("ALTER TABLE tenants ALTER COLUMN slug SET NOT NULL"))
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)")
        )
    insp = inspect(conn)
    cols = _cols(insp, "tenants")
    if "status" not in cols:
        conn.execute(
            text(
                "ALTER TABLE tenants ADD COLUMN status VARCHAR(32) "
                "NOT NULL DEFAULT 'active'"
            )
        )
    if "name" not in cols:
        conn.execute(
            text(
                "ALTER TABLE tenants ADD COLUMN name VARCHAR(200) "
                "NOT NULL DEFAULT 'Tenant'"
            )
        )
    if "created_at" not in cols:
        conn.execute(
            text(
                "ALTER TABLE tenants ADD COLUMN created_at TIMESTAMP "
                "NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        )
    if "deleted_at" not in cols:
        conn.execute(text("ALTER TABLE tenants ADD COLUMN deleted_at TIMESTAMP NULL"))


def repair() -> None:
    url = get_database_url()
    engine = create_engine(url)

    with engine.begin() as conn:
        _repair_tenants(conn)

    # create_all only adds missing tables/indexes — safe on drifted DBs.
    logger.info("create_all_missing_tables")
    Base.metadata.create_all(bind=engine)

    head = _head_revision()
    with engine.begin() as conn:
        _stamp(conn, head)

    logger.info("schema_repair_complete head=%s", head)


if __name__ == "__main__":
    try:
        repair()
    except Exception:
        logger.exception("schema_repair_failed")
        sys.exit(1)
