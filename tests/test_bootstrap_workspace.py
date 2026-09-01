import base64
import hashlib
import os
from datetime import datetime

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
import scripts.bootstrap_workspace as bootstrap_mod

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
        raise AssertionError("expected BootstrapError")
    except BootstrapError:
        pass


def test_bootstrap_creates_hashed_key_and_authenticates():
    reset_database()
    with TestingSessionLocal() as db:
        result = create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
        assert result.api_key.startswith("mbs_")
        assert result.key_prefix == result.api_key[:12]
        assert len(result.key_prefix) == 12
        tenant = db.get(Tenant, result.tenant_id)
        workspace = db.get(Workspace, result.workspace_id)
        key = db.get(ApiKey, result.key_id)
        assert tenant is not None
        assert tenant.name == "Staging Tenant"
        assert tenant.plan == "free"
        assert tenant.status == "active"
        assert tenant.subscription_status is None
        assert workspace is not None
        assert workspace.slug == "staging-workspace"
        assert workspace.tenant_id == tenant.id
        assert key is not None
        assert key.is_active is True
        assert key.key_hash == hashlib.sha256(result.api_key.encode("utf-8")).hexdigest()
        assert result.api_key not in key.key_hash
        assert result.api_key not in key.key_prefix
        assert db.query(ApiKey).count() == 1
        plaintext = result.api_key

    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": plaintext})
    assert response.status_code == 200, "bootstrapped workspace key should authenticate"
    body = response.json()
    assert body["workspace_name"] == "Staging Workspace"
    assert body["plan"] == "free"
    assert body["paid_entitlement_active"] is False


def test_inactive_bootstrapped_key_is_rejected():
    reset_database()
    with TestingSessionLocal() as db:
        result = create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
        plaintext = result.api_key
        key_id = result.key_id
    with TestingSessionLocal() as db:
        key = db.get(ApiKey, key_id)
        key.is_active = False
        key.revoked_at = datetime.utcnow()
        db.commit()
    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": plaintext})
    assert response.status_code == 401, "revoked bootstrap key must not authenticate"


def test_duplicate_bootstrap_fails_without_second_key():
    reset_database()
    with TestingSessionLocal() as db:
        create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
    with TestingSessionLocal() as db:
        try:
            create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
            raise AssertionError("expected BootstrapError")
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
            raise AssertionError("expected BootstrapError")
        except BootstrapError:
            db.rollback()
        assert db.query(Tenant).count() == 1
        assert db.query(ApiKey).count() == 1


def test_failed_cli_does_not_print_a_key(monkeypatch, capsys):
    reset_database()
    with TestingSessionLocal() as db:
        create_workspace(db, tenant_name="Staging Tenant", workspace_name="Staging Workspace")
    monkeypatch.setattr(bootstrap_mod, "validate_bootstrap_runtime", lambda: None)
    monkeypatch.setattr(bootstrap_mod, "open_session", TestingSessionLocal)

    code = bootstrap_main(["--tenant-name", "Staging Tenant", "--workspace-name", "Staging Workspace"])
    captured = capsys.readouterr()
    assert code == 1
    assert "mbs_" not in captured.out
    assert "mbs_" not in captured.err
    with TestingSessionLocal() as db:
        assert db.query(ApiKey).count() == 1


def test_placeholder_database_url_fails_closed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://memorybridge:change-me@localhost:5432/memorybridge")
    try:
        validate_bootstrap_runtime()
        raise AssertionError("expected BootstrapError")
    except BootstrapError as exc:
        assert "placeholder" in str(exc)


def test_bootstrap_does_not_require_stripe_credentials(monkeypatch):
    reset_database()
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    with TestingSessionLocal() as db:
        result = create_workspace(db, tenant_name="No Stripe Tenant", workspace_name="No Stripe Workspace")
        assert result.tenant_id
        assert db.get(Tenant, result.tenant_id).plan == "free"


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
