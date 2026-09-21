"""Bring drifted Railway/Postgres schemas up to the current models."""

from __future__ import annotations

import logging
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.database import Base, get_database_url
from app import models  # noqa: F401 — register mappers

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


def _ensure_default_tenant(conn) -> None:
    insp = inspect(conn)
    if "tenants" not in insp.get_table_names():
        return
    row = conn.execute(
        text("SELECT id FROM tenants WHERE id = :id"),
        {"id": DEFAULT_TENANT_ID},
    ).fetchone()
    if row:
        return
    conn.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status, created_at) "
            "VALUES (:id, 'Default Tenant', 'default', 'active', CURRENT_TIMESTAMP)"
        ),
        {"id": DEFAULT_TENANT_ID},
    )


def _add_col(conn, table: str, ddl: str) -> None:
    logger.warning("repairing %s.%s", table, ddl.split()[0])
    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))


def _repair_table_columns(conn) -> None:
    insp = inspect(conn)
    tables = set(insp.get_table_names())

    if "tenants" in tables:
        cols = _cols(insp, "tenants")
        if "slug" not in cols:
            _add_col(conn, "tenants", "slug VARCHAR(100)")
            conn.execute(
                text(
                    "UPDATE tenants SET slug = 'tenant-' || substr(replace(id::text, '-', ''), 1, 8) "
                    "WHERE slug IS NULL OR btrim(slug) = ''"
                )
            )
            conn.execute(
                text("UPDATE tenants SET slug = 'default' WHERE id = :id"),
                {"id": DEFAULT_TENANT_ID},
            )
            conn.execute(text("ALTER TABLE tenants ALTER COLUMN slug SET NOT NULL"))
            conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_slug ON tenants (slug)")
            )
        insp = inspect(conn)
        cols = _cols(insp, "tenants")
        if "status" not in cols:
            _add_col(conn, "tenants", "status VARCHAR(32) NOT NULL DEFAULT 'active'")
        if "name" not in cols:
            _add_col(conn, "tenants", "name VARCHAR(200) NOT NULL DEFAULT 'Tenant'")
        if "created_at" not in cols:
            _add_col(
                conn,
                "tenants",
                "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP",
            )
        if "deleted_at" not in cols:
            _add_col(conn, "tenants", "deleted_at TIMESTAMP NULL")

    _ensure_default_tenant(conn)
    insp = inspect(conn)

    if "users" in tables:
        cols = _cols(insp, "users")
        if "tenant_id" not in cols:
            _add_col(conn, "users", "tenant_id VARCHAR")
            conn.execute(
                text("UPDATE users SET tenant_id = :tid WHERE tenant_id IS NULL"),
                {"tid": DEFAULT_TENANT_ID},
            )
            conn.execute(text("ALTER TABLE users ALTER COLUMN tenant_id SET NOT NULL"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users (tenant_id)")
            )

    if "memory_records" in tables:
        cols = _cols(insp, "memory_records")
        if "tenant_id" not in cols:
            _add_col(conn, "memory_records", "tenant_id VARCHAR")
            conn.execute(
                text(
                    "UPDATE memory_records SET tenant_id = :tid WHERE tenant_id IS NULL"
                ),
                {"tid": DEFAULT_TENANT_ID},
            )
            conn.execute(
                text("ALTER TABLE memory_records ALTER COLUMN tenant_id SET NOT NULL")
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_memory_records_tenant_id "
                    "ON memory_records (tenant_id)"
                )
            )
        if "key_version" not in cols:
            _add_col(
                conn,
                "memory_records",
                "key_version INTEGER NOT NULL DEFAULT 1",
            )

    if "tenant_subscriptions" in tables:
        cols = _cols(insp, "tenant_subscriptions")
        if "last_stripe_event_ts" not in cols:
            _add_col(
                conn,
                "tenant_subscriptions",
                "last_stripe_event_ts INTEGER NOT NULL DEFAULT 0",
            )


def repair() -> None:
    url = get_database_url()
    engine = create_engine(url)

    with engine.begin() as conn:
        _repair_table_columns(conn)

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
