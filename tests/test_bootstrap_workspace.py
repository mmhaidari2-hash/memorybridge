import base64
import hashlib
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))

from app.database import Base, get_db
from app.models import ApiKey, Tenant, Workspace
from main import app
from scripts.bootstrap_workspace import (
    BootstrapError,
    create_workspace,
    main as bootstrap_main,
    validate_bootstrap_runtime,
    workspace_slug,
)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_workspace_slug_rejects_empty_name():
    try:
        workspace_slug("   ***   ")
        assert False, "expected BootstrapError"
    except BootstrapError:
        pass


def test_bootstrap_creates_hashed_key_and_authenticates(monkeypatch):
    reset_database()
    monkeypatch.setenv("APP_ENV", "development")
    with TestingSessionLocal() as db:
        result = create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
        assert result.api_key.startswith("mbs_")
        assert result.key_prefix == result.api_key[:12]
        tenant = db.get(Tenant, result.tenant_id)
        workspace = db.get(Workspace, result.workspace_id)
        key = db.get(ApiKey, result.key_id)
        assert tenant is not None and tenant.name == "Staging Tenant" and tenant.plan == "free"
        assert workspace is not None and workspace.slug == "staging-workspace"
        assert workspace.tenant_id == tenant.id
        assert key is not None and key.is_active is True
        assert key.key_hash == hashlib.sha256(result.api_key.encode("utf-8")).hexdigest()
        assert result.api_key not in key.key_hash
        assert result.api_key not in key.key_prefix
        assert db.query(ApiKey).count() == 1

    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": result.api_key})
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == result.workspace_id
    assert body["workspace_name"] == "Staging Workspace"
    assert body["plan"] == "free"
    assert body["paid_entitlement_active"] is False


def test_duplicate_bootstrap_fails_without_second_key():
    reset_database()
    with TestingSessionLocal() as db:
        create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
    with TestingSessionLocal() as db:
        try:
            create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
            assert False, "expected BootstrapError"
        except BootstrapError:
            db.rollback()
        assert db.query(Tenant).count() == 1
        assert db.query(Workspace).count() == 1
        assert db.query(ApiKey).count() == 1


def test_duplicate_workspace_name_on_other_tenant_fails_safely():
    reset_database()
    with TestingSessionLocal() as db:
        create_workspace(db, tenant_name="Tenant A", workspace_name="Shared Name")
    with TestingSessionLocal() as db:
        try:
            create_workspace(db, tenant_name="Tenant B", workspace_name="Shared Name")
            assert False, "expected BootstrapError"
        except BootstrapError:
            db.rollback()
        assert db.query(Tenant).count() == 1
        assert db.query(ApiKey).count() == 1


def test_placeholder_database_url_fails_closed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://memorybridge:change-me@localhost:5432/memorybridge")
    try:
        validate_bootstrap_runtime()
        assert False, "expected BootstrapError"
    except BootstrapError as exc:
        assert "placeholder" in str(exc)


def test_missing_required_cli_names_returns_nonzero():
    try:
        bootstrap_main([])
        raise AssertionError("expected argparse to exit")
    except SystemExit as exc:
        assert exc.code == 2
    try:
        bootstrap_main(["--tenant-name", "Only Tenant"])
        raise AssertionError("expected argparse to exit")
    except SystemExit as exc:
        assert exc.code == 2
